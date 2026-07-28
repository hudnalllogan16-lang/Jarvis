"""Operator HTTP API (spec §12.5, §1).

Every response in this module is in operator vocabulary. §1 requires the UI to
expose business concepts — Company, Budget, Profit, Health, Approval — and never
infrastructure concepts, and §12.5 makes that binding rather than cosmetic. So
the translation happens here, at the boundary, not in the browser: no route
returns a workflow id, a capability name, a token count, or a retry state.

The drill-down route is the single exception, and it is opt-in by construction —
nothing in the default view links to it without the operator choosing it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from jarvis.api.pending_update import PendingUpdateView, render_plan
from jarvis.api.render import render_doing_now, render_operator_text
from jarvis.approvals.models import OPERATOR_LABELS as APPROVAL_LABELS
from jarvis.approvals.models import ApprovalRequest, ApprovalState
from jarvis.approvals.rendering import (
    payload_is_correctable,
    render_detail,
    render_payload,
    render_request,
)
from jarvis.approvals.service import ApprovalError
from jarvis.budget.ledger import BudgetLedger
from jarvis.domain.contract import BusinessContract
from jarvis.domain.lifecycle import OPERATOR_LABELS as LIFECYCLE_LABELS
from jarvis.domain.lifecycle import LifecycleState
from jarvis.domain.refresh import ContractRefreshPlan, RefreshConsent, RefreshOutcome
from jarvis.kernel.container import KernelServices, PlatformKernel
from jarvis.kernel.errors import BusinessNotFoundError, JarvisError
from jarvis.kernel.ids import BusinessId, BusinessTypeName, DecisionId, new_decision_id
from jarvis.kernel.logging import get_logger
from jarvis.kpi.engine import KpiEngine
from jarvis.notifications.service import NotificationService
from jarvis.persistence.models import DeadLetterRow

logger = get_logger(__name__)

STATIC_DIR = "jarvis/api/static"

MAX_KPI_SERIES_LIMIT = 365
"""Upper bound on `?limit=` for `/kpi-series` (M9-2a). One reading a day for a
year is already more than a trend line needs; the bound exists so the query
`KpiEngine.series` runs stays cheap regardless of what a client passes, the
same reasoning `target_value`'s own bounds protect the contract side."""

UPDATE_CHECK_UNCERTAIN_NOTE = (
    "Jarvis couldn't check whether an update is ready for this company just now — "
    "it will try again on its own."
)
"""M9-3 surface backlog item 6 (M9-F45): 'up-to-date vs uncomputable both silent'. Both
states used to render as nothing at all — see `_pending_update`'s own docstring
— which is honest for one of them (design PLUGIN-FRAMEWORK.md Part 4.3's
"simply current" case, where silence is correct and stays correct) and
misleading for the other (the operator cannot distinguish "nothing to show
you" from "Jarvis could not tell"). One line, shown only for the second case,
is the whole fix — the first stays exactly as silent as it always was."""


class CreateCompanyBody(BaseModel):
    """Operator input to the create-a-company flow (spec §4).

    Four fields, because §4 scopes the wizard to instantiating known types and
    §12.5 keeps the default experience to naming a company and starting it.
    Everything else comes from the type definition.
    """

    template: str
    name: str
    budget_usd: float | None = None
    per_round_limit_usd: float | None = Field(default=None, gt=0)
    """The most this company may spend on one round of work. Optional to send,
    never absent on the company: left out, it takes the platform's configured
    limit, and that choice is recorded (M6-F23). Named for what an owner
    understands rather than for the machinery underneath (§12.5)."""


class DecideBody(BaseModel):
    """Operator's answer to an approval."""

    reason: str = ""
    modified_parameters: dict[str, Any] | None = None
    """Corrected effect payload (A-003). May change the value of a field the
    approval already carries; may not introduce one. See `_decide`."""


def create_app(kernel: PlatformKernel) -> FastAPI:
    """Build the operator API.

    Args:
        kernel: Initialised Platform Kernel, injected so tests can supply one
            backed by an in-memory database.

    Returns:
        A configured FastAPI application.
    """
    app = FastAPI(title="Jarvis", docs_url="/api/docs")

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Turn a raw Pydantic 422 into one plain sentence, and log the detail.

        FastAPI's default handler returns the full validation error list — field
        paths, error types, inputs — straight to the browser. That is diagnostic
        output in the operator's face, which §12.5 forbids in the default view.
        The technical detail is what a developer needs, so it goes to the log; the
        operator gets a sentence they can act on.

        This is a safety net, not the primary defense: a validation error reaching
        here means the UI sent a shape the API didn't expect (as the duplicate
        request-model bug did), so the detail is logged at warning to stay visible.
        """
        logger.warning(
            "request validation failed",
            extra={
                "context": {
                    "path": request.url.path,
                    "errors": [
                        {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
                        for e in exc.errors()
                    ],
                }
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "Jarvis couldn't read that request. Please try again."},
        )

    async def _type_catalog(svc: KernelServices) -> dict[str, dict[str, str]]:
        """Map an installed type's name to its operator-facing display data.

        Reads only what `ProvisioningService.install`/`install_business_type`
        already stores (D-007's "company template" name, plus the description
        installed alongside it in `plugin_metadata` — the same values
        `/api/company-templates` already exposes to the create-a-company
        flow). No new write path, no model involvement: a type's kind and
        blurb are as stored-value as a KPI target's `operator_label` (D-011's
        shape, applied to a type instead of a number).

        M7-5 verdict item 1: a company's kind is invisible once it exists —
        the card names the company but never says what kind of company it
        is, and Details never repeats the type's own promise (for Finance,
        "it places no trades and moves no money"). All three live companies
        rendered identically once created.
        """
        return {
            row.name: {
                "kind": row.display_name,
                "kind_description": (row.plugin_metadata or {}).get("description", ""),
            }
            for row in await svc.registry.installed_types()
        }

    async def _goal_readings(
        svc: KernelServices, contract: BusinessContract
    ) -> list[dict[str, Any]]:
        """Per-metric measured-vs-target readings for the goals drill-down.

        M7-5 verdict item 2: `health_parts`' "Hitting its goals" is one number
        with nowhere to ask what it means. This is that answer — reusing
        `KpiEngine.latest`, the exact per-key read `attainment()` already does
        for the score, so nothing new is queried here or in the engine.

        Labels come from the type's own `KpiTarget.operator_label` — plain
        language, never `key: revenue_mtd` (spec §12.5). A target stored
        without one — not reachable through any installed type today, since
        the field is required — falls back to its key with underscores
        turned to spaces rather than surfacing raw `snake_case`.
        """
        engine = KpiEngine(svc.session)
        out: list[dict[str, Any]] = []
        for target in contract.kpi_targets:
            actual = await engine.latest(contract.business_id, target.key)
            out.append(
                {
                    "label": target.operator_label or target.key.replace("_", " ").capitalize(),
                    "measured": float(actual) if actual is not None else None,
                    "target": float(target.target_value),
                    "unit": target.unit,
                    "direction": target.direction.value,
                }
            )
        return out

    async def _ever_measured(svc: KernelServices, contract: BusinessContract) -> bool:
        """Whether any of this company's KPI targets has a recorded observation.

        M7-5b item 4 (lower-priority half): `KpiEngine.attainment()` scores a
        target with no observation yet identically to one measured and scored
        a genuine zero — both are simply skipped out of the ratio, and "no
        ratios" and "every ratio zero" both read as `attainment == 0` (D-020's
        `zero_attainment_stall` cannot tell them apart from that one integer).
        Reuses `KpiEngine.latest`, the exact per-key read `attainment()`
        already performs — no new query — so this is cheap, and is called
        only for the one band (`zero_attainment_stall`) where the distinction
        changes the sentence.
        """
        if not contract.kpi_targets:
            return False
        engine = KpiEngine(svc.session)
        for target in contract.kpi_targets:
            if await engine.latest(contract.business_id, target.key) is not None:
                return True
        return False

    async def _pending_update(
        svc: KernelServices, contract: BusinessContract, types: dict[str, dict[str, str]]
    ) -> tuple[PendingUpdateView | None, bool]:
        """Whether this company has a pending Band-B template update to show.

        design `PLUGIN-FRAMEWORK.md` Part 4/6 (D-030, M8-F115). `plan_refresh`
        needs `BusinessTypeDefinition` (`jarvis.businesses`, milestone 5), a
        forward import this milestone-3 module may not make even locally
        (`tests/test_layering.py` walks the whole AST, not just top-level
        imports) — so the service is built by the Kernel, the composition
        root that may, and handed here session-scoped, the same M6-F20
        pattern `build_approvals` already uses. This route reads only the
        typed `ContractRefreshPlan` (`jarvis.domain.refresh`, milestone 1),
        which is safe to import directly (container.py's own reasoning for
        why the plan and result models live there rather than beside their
        producer).

        Returns:
            `(view, uncertain)`. `view` is `None` either when the company is
            simply current (Part 4.3's negative control — the correct,
            silent default) or when the plan could not be computed at all;
            `uncertain` is what tells those two apart. A refusal to compute
            the plan — the type this company was built from is no longer
            installed, or refreshing it against the installed definition
            would itself be invalid (M8-F111 refuses this at install for
            every *new* upgrade, but a row installed before that guard
            existed could still be in this state) — used to answer plain
            `None`, indistinguishable from "up to date" (M9-3 surface
            backlog item 6, `UPDATE_CHECK_UNCERTAIN_NOTE`). There is still
            nothing here an operator could act on either way — Part 4.3's
            reasoning for silence-as-default is unchanged — but "nothing to
            show you" and "couldn't tell" are no longer the same silence.

        Args:
            types: The installed-type display-data map `_type_catalog`
                already builds for the card, reused here for the sentence
                Part 6's worked example phrases: "The {type} setup has
                changed since this company was created."
        """
        refresh = kernel.build_refresh(svc)
        try:
            plan: ContractRefreshPlan = await refresh.plan_refresh(contract.business_id)
        except JarvisError as exc:
            logger.warning(
                "pending-update plan could not be computed",
                extra={
                    "context": {
                        "business_id": contract.business_id,
                        "failure_class": type(exc).__name__,
                    }
                },
            )
            return None, True
        kind = types.get(contract.business_type, {}).get("kind") or "your company template"
        view = render_plan(plan, company_name=contract.display_name, type_display_name=kind)
        return view, False

    def _stuck_reading(stuck_count: int) -> str:
        """Plain-language reading of the stuck-work part (M7-5b item 1).

        Was labelled "Rounds completed" over `health.reliability` — a bare
        0-100 penalty score (`max(0, 100 - stuck_count*20)`, engine.py) that
        counts no rounds and completes nothing; a company mid-way through a
        feed of failed rounds could still read 100. D-007's own phrasing for
        this fact is "[Company] got stuck", so the label states the same
        reading `_summarise`'s stuck branch already uses, honestly, as the
        label rather than a noun the number cannot support. The metric
        (`reliability`, still the value shown beside it) is untouched.
        """
        if stuck_count == 0:
            return "Nothing stuck"
        noun = "task" if stuck_count == 1 else "tasks"
        return f"{stuck_count} {noun} stuck"

    async def _company_payload(
        svc: KernelServices, row: Any, types: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        """Assemble one company card (spec §12.5's default view)."""
        contract = await svc.registry.get_contract(BusinessId(row.business_id))
        ledger = kernel.build_ledger(svc)
        spend = await ledger.business_spend(BusinessId(row.business_id))
        health = await KpiEngine(svc.session).health(contract, spend_usd=spend)
        feed = await svc.decisions.activity_feed(BusinessId(row.business_id), limit=1)
        state = LifecycleState(row.lifecycle_state)
        kind = types.get(row.business_type, {})

        health_reason = health.summary
        if health.zero_attainment_stall and not await _ever_measured(svc, contract):
            # M7-5b item 4 (lower-priority half): the card said "Set goals
            # but hasn't hit any of them yet." — which reads as a tried-and-
            # missed goal — for a company whose goals drill-down shows every
            # target still unmeasured. Same band (`watch` is unaffected),
            # honest wording for the sub-case the number alone cannot tell
            # apart from a real miss.
            health_reason = "Set goals, but nothing's been measured yet."
        elif health.early_days and not await _ever_measured(svc, contract):
            # M9-3 surface backlog item 4 (M9-F43), the `healthy`-band twin
            # of the fix above: `early_days` keeps the badge at `healthy` (D-027.4
            # — a young company is genuinely fine), but `_summarise`'s own
            # EARLY_DAYS_SUMMARY ("Just getting started — no goals hit
            # yet.") still reads as an attempt that came up short. Reusing
            # `_ever_measured` — already computed for the sibling branch,
            # no new query, no kpi/engine.py change — distinguishes "hit
            # nothing" from "nothing to hit yet" the same way the watch-band
            # case already does. `zero_attainment_stall` and `early_days`
            # are mutually exclusive (kpi/engine.py's `health()`), so this
            # never double-applies.
            health_reason = "Just getting started — nothing's been measured yet."

        return {
            "id": row.business_id,
            "name": row.display_name,
            "kind": kind.get("kind", row.business_type),
            "kind_description": kind.get("kind_description", ""),
            "status": LIFECYCLE_LABELS[state],
            "running": state is LifecycleState.ACTIVE,
            "health": health.score,
            "health_band": health.band,
            "health_reason": health_reason,
            "health_parts": {
                "Budget left": health.budget_headroom,
                _stuck_reading(health.stuck_count): health.reliability,
                "Hitting its goals": health.kpi_attainment,
            },
            "spent": float(spend),
            "budget": float(contract.budget.business_cap_usd),
            "per_round_limit": float(contract.budget.wake_cycle_ceiling_usd),
            # Live Manager prose, laundered at the render boundary (§12.5,
            # M6-5a item 4) and capped to one sentence — the card is the
            # default view, not the drill-down.
            "doing": render_doing_now(feed[0].summary) if feed else "Nothing yet.",
        }

    @app.get("/api/companies")
    async def list_companies() -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """Return every company as a card (spec §12.5 default view)."""
        async with kernel.services() as svc:
            rows = await svc.registry.list_instances()
            types = await _type_catalog(svc)
            return [await _company_payload(svc, row, types) for row in rows]

    @app.get("/api/companies/{business_id}")
    async def company_detail(  # pyright: ignore[reportUnusedFunction]
        business_id: str,
    ) -> dict[str, Any]:
        """Return one company with its activity feed.

        The feed is the Decision Log (spec §11.5) — "What [Company] is doing" —
        and is the first and only answer to a "why" question at this level.
        """
        async with kernel.services() as svc:
            try:
                rows = await svc.registry.list_instances()
                row = next(r for r in rows if r.business_id == business_id)
            except StopIteration:
                raise HTTPException(404, "No company with that id.") from None

            types = await _type_catalog(svc)
            payload = await _company_payload(svc, row, types)
            contract = await svc.registry.get_contract(BusinessId(business_id))
            # Opt-in drill-down (§12.5): reached only when the operator opens
            # Details, never eagerly on the card list above.
            payload["goals"] = await _goal_readings(svc, contract)
            # design PLUGIN-FRAMEWORK.md Part 4/6 (D-030): a pending template
            # update lives on the company's own page, never in the approvals
            # queue. See `_pending_update`.
            update, update_uncertain = await _pending_update(svc, contract, types)
            payload["pending_update"] = (
                {
                    "headline": update.headline,
                    "intro": update.intro,
                    "changes": list(update.changes),
                }
                if update
                else None
            )
            # M9-3 item 6: the one honest line for "couldn't check", never
            # shown alongside a real `pending_update` (mutually exclusive by
            # construction — `_pending_update` only sets `uncertain` on the
            # branch that returns no view) and never shown for the ordinary
            # up-to-date case, which stays silent exactly as before.
            payload["pending_update_note"] = (
                UPDATE_CHECK_UNCERTAIN_NOTE if update_uncertain else None
            )
            feed = await svc.decisions.activity_feed(BusinessId(business_id), limit=40)
            payload["activity"] = [
                {
                    "when": entry.decided_at.isoformat(),
                    # Full text here (unlike the card's capped "doing"): this
                    # is the drill-down §12.5 promises the truncated summary
                    # a home in.
                    "what": render_operator_text(entry.summary),
                    "why": render_operator_text(entry.rationale),
                }
                for entry in feed
            ]

            stuck = await svc.session.scalars(
                select(DeadLetterRow)
                .where(DeadLetterRow.business_id == business_id)
                .where(DeadLetterRow.resolved.is_(False))
            )
            payload["stuck"] = [
                {"id": row.invocation_id, "what": row.operator_summary} for row in stuck.all()
            ]

            approvals = kernel.build_approvals(svc)
            payload["can_do_alone"] = [
                counter.action_type
                for counter in await approvals.graduated_actions(BusinessId(business_id))
            ]
            return payload

    @app.get("/api/company-templates")
    async def company_templates() -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """Return installed types the operator can create a company from (§4)."""
        async with kernel.services() as svc:
            provisioning = kernel.build_provisioning(svc)
            return [
                {
                    "id": definition.name,
                    "name": definition.display_name,
                    "what_it_does": definition.description,
                    "suggested_budget": float(definition.suggested_budget_usd),
                    "suggested_round_limit": float(definition.suggested_wake_ceiling_usd),
                }
                for definition in await provisioning.available_types()
            ]

    @app.post("/api/company-templates/install-builtin")
    async def install_builtin_templates() -> (  # pyright: ignore[reportUnusedFunction]
        dict[str, object]
    ):
        """Install the built-in company templates on demand (first-run recovery).

        The built-ins install automatically at startup via ensure_builtin_types.
        This route exists so that an empty-template state in the UI is never a
        dead end: if startup installation was skipped or a database was reset, the
        operator has a one-click path to a working system rather than a message
        telling them what's wrong and stopping there.

        Idempotent — ensure_builtin_types installs only what's missing, so calling
        it when templates already exist is harmless.

        `not_ready_count` surfaces how many built-ins this call could not
        install (design Part 2.3, M8-F2): before, a contained failure logged a
        warning nobody watching the UI would ever see, and the operator's only
        signal was templates that were fewer than expected with no count and
        no reason attached.
        """
        report = await kernel.ensure_builtin_types()
        async with kernel.services() as svc:
            installed = [t.name for t in await svc.registry.installed_types()]
        return {
            "installed": installed,
            "not_ready_count": len(report.skipped),
            "status": "Templates ready." if not report.skipped else "Some templates aren't ready.",
        }

    @app.post("/api/companies")
    async def create_company(  # pyright: ignore[reportUnusedFunction]
        body: CreateCompanyBody,
    ) -> dict[str, str]:
        """Create and start a company from an installed type (spec §4, §12.5).

        §12.5 lists "create/pause a company" as a primary operator action. Until
        this route existed the Registry was unreachable from outside the process
        and no company could be created at all.
        """
        async with kernel.services() as svc:
            provisioning = kernel.build_provisioning(svc)
            definition = next(
                (d for d in await provisioning.available_types() if d.name == body.template),
                None,
            )
            if definition is None:
                raise HTTPException(404, "That company template isn't installed.")
            try:
                business_id = await provisioning.create_company(
                    definition=definition,
                    display_name=body.name.strip(),
                    budget_usd=Decimal(str(body.budget_usd)) if body.budget_usd else None,
                    wake_ceiling_usd=(
                        Decimal(str(body.per_round_limit_usd)) if body.per_round_limit_usd else None
                    ),
                )
            except JarvisError as exc:
                raise HTTPException(409, exc.operator_message) from exc
            return {"id": business_id, "status": "Running"}

    @app.get("/api/approvals")
    async def list_approvals() -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """Return the "Needs your OK" queue (spec §8, §12.5).

        Each item carries the four facts §8 requires be displayed, rendered from
        stored values rather than regenerated as prose — and, since D-024.1 made
        the approval's parameters the bytes an effect actually publishes, the
        payload itself. An operator authorising a publish is authorising those
        bytes, so they are part of the request, not a detail behind it.
        """
        async with kernel.services() as svc:
            service = kernel.build_approvals(svc)
            out: list[dict[str, Any]] = []
            for row in await service.pending():
                contract = await svc.registry.get_contract(BusinessId(row.business_id))
                request = ApprovalRequest(
                    approval_id=row.approval_id,
                    business_id=BusinessId(row.business_id),
                    action_type=row.action_type,
                    action_summary=row.action_summary,
                    amount_usd=Decimal(str(row.amount_usd)) if row.amount_usd else None,
                    counterparty=row.counterparty,
                    triggering_condition=row.triggering_condition,
                    downside=row.downside,
                )
                # "What happens" duplicates the card's own h2 (both render from
                # `render_request`) — the same fact once as the headline, once
                # more as the first row of the grid beneath it. Dropped here,
                # at the API boundary, rather than from `render_detail`
                # itself: the other three §8 facts it returns are still a
                # complete, independently useful set for any caller that has
                # no headline of its own to pair it with.
                detail = render_detail(request, contract.display_name)
                detail.pop("What happens", None)
                out.append(
                    {
                        "id": row.approval_id,
                        "company": contract.display_name,
                        "company_id": row.business_id,
                        "ask": render_request(request, contract.display_name),
                        "detail": detail,
                        "payload": render_payload(row.parameters),
                        "payload_correctable": payload_is_correctable(row.parameters),
                        "amount": float(row.amount_usd) if row.amount_usd else None,
                        "waiting_since": row.requested_at.isoformat(),
                        "state": APPROVAL_LABELS[ApprovalState.PENDING],
                    }
                )
            return out

    @app.post("/api/approvals/{approval_id}/approve")
    async def approve(  # pyright: ignore[reportUnusedFunction]
        approval_id: str, body: DecideBody
    ) -> dict[str, str]:
        """Approve a pending request."""
        return await _decide(approval_id, body, approve=True)

    @app.post("/api/approvals/{approval_id}/deny")
    async def deny(  # pyright: ignore[reportUnusedFunction]
        approval_id: str, body: DecideBody
    ) -> dict[str, str]:
        """Deny a pending request."""
        return await _decide(approval_id, body, approve=False)

    async def _decide(approval_id: str, body: DecideBody, *, approve: bool) -> dict[str, str]:
        """Record the operator's answer and let the Manager hear about it (D-006).

        The service is built by the Kernel rather than constructed here, and
        that is the whole of the round trip. `ApprovalService` publishes
        `approval.decided` only if it holds an event bus; this route built one
        without, so the decision was recorded and no Manager was ever woken —
        the M5-F4 defect, reopened one layer out at the only place an operator
        actually decides anything. `test_no_module_builds_an_unwired_approval
        _service` keeps it closed mechanically.

        A correction may change the value of a field the approval already
        carries and may not introduce one. The operator's authority over the
        action is §8's whole point, so the *values* are theirs to change; the
        set of fields is the tool's parameter contract (D-024.1), and a field
        nobody was shown is a field nobody approved. M6-F30 is what that looks
        like when it goes wrong from the model's side — `webhook_url` arriving
        as an action parameter — and the operator's side of the same surface
        should not be the way back in.
        """
        refusal: str | None = None
        async with kernel.services() as svc:
            service = kernel.build_approvals(svc)
            pending = {row.approval_id: row for row in await service.pending()}
            row = pending.get(approval_id)
            if row is None:
                raise HTTPException(404, "You've already answered this one.")
            contract = await svc.registry.get_contract(BusinessId(row.business_id))

            added = (
                sorted(set(body.modified_parameters) - set(row.parameters))
                if approve and body.modified_parameters is not None
                else []
            )
            if added:
                # Recorded here, refused after this scope closes: `services()`
                # rolls back on exception, so raising inside would discard the
                # record of the attempt along with the attempt.
                await svc.audit.record(
                    event_type="approval.correction_refused",
                    actor="operator",
                    business_id=BusinessId(row.business_id),
                    payload={
                        "approval_id": approval_id,
                        # Bounded: these names came off the wire, and an audit
                        # entry is not a place to store whatever was sent.
                        "added_fields": [name[:200] for name in added[:20]],
                        "reason": "a correction may change what was shown, never add to it",
                    },
                )
                refusal = "You can change what's here, but not add anything new to it."
            else:
                decision_id: DecisionId = new_decision_id()
                try:
                    if approve:
                        await service.approve(
                            approval_id,
                            contract=contract,
                            decision_id=decision_id,
                            modified_parameters=body.modified_parameters,
                        )
                    else:
                        await service.deny(
                            approval_id,
                            contract=contract,
                            decision_id=decision_id,
                            reason=body.reason,
                        )
                except ApprovalError as exc:
                    raise HTTPException(409, exc.operator_message) from exc
                # The notification that asked for this decision no longer
                # needs to sit in the queue once the decision exists (M6-5a
                # item 5, §12.5 "no permanent accumulation"). Same session as
                # the decision itself, so both commit or neither does.
                await NotificationService(svc.session).resolve_for(approval_id)

        if refusal is not None:
            raise HTTPException(409, refusal)
        return {"status": "approved" if approve else "denied"}

    @app.post("/api/companies/{business_id}/pause")
    async def pause(business_id: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Pause a company (spec §12.5: a primary operator action)."""
        return await _transition(business_id, LifecycleState.PAUSED, "You paused this company.")

    @app.post("/api/companies/{business_id}/resume")
    async def resume(business_id: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Resume a paused company."""
        return await _transition(business_id, LifecycleState.ACTIVE, "You started this company.")

    async def _transition(business_id: str, target: LifecycleState, reason: str) -> dict[str, str]:
        async with kernel.services() as svc:
            try:
                await svc.registry.transition(
                    BusinessId(business_id),
                    target,
                    decision_id=new_decision_id(),
                    reason=reason,
                )
            except JarvisError as exc:
                raise HTTPException(409, exc.operator_message) from exc
            return {"status": LIFECYCLE_LABELS[target]}

    @app.post("/api/companies/{business_id}/revoke/{action_type}")
    async def revoke(  # pyright: ignore[reportUnusedFunction]
        business_id: str, action_type: str
    ) -> dict[str, str]:
        """Make an action need approval again (spec §12.5).

        §12.5 requires graduation be shown "with an easy way to revoke it".
        """
        async with kernel.services() as svc:
            service = kernel.build_approvals(svc)
            await service.revoke_graduation(BusinessId(business_id), action_type)
            return {"status": "This needs your OK again."}

    @app.post("/api/companies/{business_id}/pending-update/apply")
    async def apply_pending_update(  # pyright: ignore[reportUnusedFunction]
        business_id: str,
    ) -> dict[str, str]:
        """Consent to a pending template update — never through §8 (D-030).

        design `PLUGIN-FRAMEWORK.md` Part 4.3/4.4: an explicit operator action
        distinct from the approvals queue — the route carries no
        `action_type`, so it structurally cannot graduate (D-030's whole
        point). The plan is recomputed here, inside this request's
        transaction, rather than trusting a client-supplied plan identifier:
        there is no request body naming one, and D-030's consent is to
        "whatever this company's pending update currently is", which only the
        platform's own stored values can answer (D-011's discipline, applied
        to what the operator is consenting to rather than only to what they
        are shown).
        """
        async with kernel.services() as svc:
            refresh = kernel.build_refresh(svc)
            try:
                plan: ContractRefreshPlan = await refresh.plan_refresh(BusinessId(business_id))
            except BusinessNotFoundError as exc:
                raise HTTPException(404, exc.operator_message) from exc
            except JarvisError as exc:
                raise HTTPException(409, exc.operator_message) from exc
            if plan.is_empty:
                raise HTTPException(409, "This isn't ready to apply yet. Check back soon.")
            try:
                result = await refresh.apply_refresh(
                    BusinessId(business_id),
                    plan,
                    consent=RefreshConsent(plan_key=plan.plan_key, granted=True),
                )
            except JarvisError as exc:
                raise HTTPException(409, exc.operator_message) from exc
        status = "Updated." if result.outcome is RefreshOutcome.APPLIED else "Already up to date."
        return {"status": status}

    @app.post("/api/companies/{business_id}/pending-update/dismiss")
    async def dismiss_pending_update(  # pyright: ignore[reportUnusedFunction]
        business_id: str,
    ) -> dict[str, str]:
        """Decline a pending template update for now (design Part 4.3).

        "Not now" is a real, recorded outcome, not a deferral loop — re-offered
        only on the next version change (M8-F102 closed, M9-4). The decline is
        stored (`BusinessRegistry.record_refresh_decline`) and `plan_refresh`
        reads it back on every subsequent call for this company, so the next
        visit answers "nothing pending" honestly rather than showing the same
        offer again — the audit Finding 3 gap this closes.
        """
        async with kernel.services() as svc:
            refresh = kernel.build_refresh(svc)
            try:
                plan = await refresh.plan_refresh(BusinessId(business_id))
            except BusinessNotFoundError as exc:
                raise HTTPException(404, exc.operator_message) from exc
            except JarvisError as exc:
                raise HTTPException(409, exc.operator_message) from exc
            if plan.is_empty:
                raise HTTPException(409, "This isn't ready yet. Check back soon.")
            try:
                await refresh.decline_refresh(
                    BusinessId(business_id),
                    plan,
                    consent=RefreshConsent(plan_key=plan.plan_key, granted=False),
                )
            except JarvisError as exc:
                raise HTTPException(409, exc.operator_message) from exc
        return {"status": "Not now."}

    @app.get("/api/settings/subsystems")
    async def subsystems() -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """What Jarvis can run, with each part's toggle state (D-017)."""
        async with kernel.services() as svc:
            rows = await svc.registry.installed_types()
            instances = await svc.registry.list_instances()
            counts: dict[str, int] = {}
            for instance in instances:
                counts[instance.business_type] = counts.get(instance.business_type, 0) + 1
            return [
                {
                    "id": row.name,
                    "name": row.display_name,
                    "enabled": bool(getattr(row, "enabled", True)),
                    "companies": counts.get(row.name, 0),
                }
                for row in rows
            ]

    @app.post("/api/settings/subsystems/{name}")
    async def toggle_subsystem(  # pyright: ignore[reportUnusedFunction]
        name: str, body: dict[str, bool]
    ) -> dict[str, str]:
        """Enable or disable one company template.

        Turning a template off hides it from "New company". Companies that
        already exist keep their own running/paused state — that separation is
        deliberate (D-017), so one switch cannot silently pause businesses.
        """
        async with kernel.services() as svc:
            try:
                await svc.registry.set_type_enabled(
                    BusinessTypeName(name), enabled=bool(body.get("enabled", True))
                )
            except JarvisError as exc:
                raise HTTPException(404, exc.operator_message) from exc
        return {"status": "Saved."}

    @app.get("/api/notifications")
    async def notifications() -> list[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        """Return unread notifications in operator language.

        `title`/`body` are stored, not templated (spec §12.5's own reasoning
        for why: a stack trace or error code never gets a chance to reach a
        field the dashboard renders). But `body` in particular can carry a
        live Manager's `action_summary` prose (`request_approval`,
        `jarvis/manager/activities.py`) — the same kind of model-authored
        text the Decision Log carries — so it needs the same laundering
        before it reaches the strip (M6 product re-review F6): platform ids
        stripped, raw lifecycle words translated, and a §12.5 technical-term
        fallback. Full text, uncapped, like the activity feed's "what"/"why"
        — a notification is already one or two sentences, not the card's
        one-line "Latest update", so `DOING_NOW_LIMIT` does not apply here
        (M7-F44: this comment named the card's label before it was renamed).
        """
        async with kernel.services() as svc:
            service = NotificationService(svc.session)
            return [
                {
                    "id": row.notification_id,
                    "title": render_operator_text(row.title),
                    "body": render_operator_text(row.body),
                    "kind": row.kind,
                    "when": row.created_at.isoformat(),
                }
                for row in await service.unread()
            ]

    @app.post("/api/notifications/{notification_id}/dismiss")
    async def dismiss_notification(  # pyright: ignore[reportUnusedFunction]
        notification_id: str,
    ) -> dict[str, str]:
        """Dismiss one notification by hand (spec §12.5: no permanent
        accumulation). Approval-linked notifications usually clear themselves
        when the approval is decided (see `_decide`); this is the operator's
        own control for the rest."""
        async with kernel.services() as svc:
            await NotificationService(svc.session).mark_read(notification_id)
        return {"status": "Dismissed."}

    @app.get("/api/summary")
    async def summary() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """Return the top status strip: companies, spend today, things waiting."""
        async with kernel.services() as svc:
            rows = await svc.registry.list_instances()
            ledger = BudgetLedger(
                svc.session,
                platform_ceiling_usd=kernel.settings.budget.platform_rolling_24h_usd,
            )
            spend = await ledger.platform_spend_24h()
            service = kernel.build_approvals(svc)
            ceiling = kernel.settings.budget.platform_rolling_24h_usd
            return {
                "companies": len(rows),
                "running": sum(1 for r in rows if r.lifecycle_state == LifecycleState.ACTIVE.value),
                "spent_today": float(spend),
                "spend_limit": float(ceiling),
                "spending_paused": spend >= ceiling,
                "waiting_on_you": len(await service.pending()),
            }

    @app.get("/api/health")
    async def health() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        """Live health for the dashboard banner (M6-5a item 8: M6-5's false-red).

        `jarvis/shell/launcher.py` registers a richer version of this same
        route — it adds the Supervisor's own part statuses (a restarting
        worker shows as "restarting itself" rather than a dead terminal) —
        but that route only exists under the full developer-shell topology.
        Running the API standalone (`jarvis.api.server`, and this test
        client) served no `/api/health` at all: the dashboard's `fetch`
        against it 404'd, `paintHealth()`'s `.filter` then threw on the
        shape it got back, and the banner read "Jarvis isn't responding" —
        false, since everything else was working.

        `jarvis.shell` is milestone 5 and this package is milestone 3
        (`tests/test_layering.py`), so the checks below intentionally do not
        import `jarvis.shell.preflight` — that would be a forward import
        outside a composition root. They are the same three checks
        (database, workflow runtime, model configuration) against the same
        `PlatformKernel`, kept in sync by hand; genuinely sharing one
        implementation across both milestones is an architecture question
        (moving the check or exempting this file), not a small fix, so it is
        flagged rather than decided here. `parts` is always empty in this
        topology — there is no Supervisor to ask — which the dashboard
        already treats as "nothing to report" rather than an error.
        """
        components: list[dict[str, object]] = []
        try:
            async with kernel.services() as svc:
                await svc.session.execute(text("SELECT 1"))
        except Exception:
            components.append(
                {
                    "name": "database",
                    "status": "down",
                    "summary": "Jarvis can't reach its database.",
                    "remedy": "Is Docker running? `docker compose up -d` starts everything.",
                }
            )
        else:
            components.append(
                {"name": "database", "status": "ok", "summary": "Database is ready.", "remedy": ""}
            )

        client = await kernel.temporal_client()
        if client is None:
            components.append(
                {
                    "name": "workflows",
                    "status": "degraded",
                    "summary": (
                        "Companies can't act right now — the part that runs them isn't reachable."
                    ),
                    "remedy": "Check `docker compose ps`; the temporal service may still "
                    "be starting.",
                }
            )
        else:
            components.append(
                {"name": "workflows", "status": "ok", "summary": "Companies can run.", "remedy": ""}
            )

        try:
            kernel.settings.llm.require_api_key()
            thinking_ok = bool(kernel.settings.llm.model)
            thinking_summary = "Model is configured." if thinking_ok else "No model is configured."
        except Exception:
            thinking_ok = False
            thinking_summary = "Companies can't think yet — no model key is configured."
        components.append(
            {
                "name": "thinking",
                "status": "ok" if thinking_ok else "degraded",
                "summary": thinking_summary,
                "remedy": ""
                if thinking_ok
                else "Set JARVIS_LLM__API_KEY in .env, or use ollama for local-only.",
            }
        )

        return {
            "ok": all(c["status"] == "ok" for c in components),
            "can_serve": next(
                (c["status"] != "down" for c in components if c["name"] == "database"), True
            ),
            "components": components,
            "parts": [],
        }

    @app.get("/api/companies/{business_id}/full-details")
    async def full_details(  # pyright: ignore[reportUnusedFunction]
        business_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Raw audit detail (spec §11).

        §12.5 calls this "Full details" and requires it be drill-down only,
        never the default view. It is a separate route for exactly that reason:
        nothing renders it unless the operator asks.
        """
        async with kernel.services() as svc:
            rows = await svc.audit.for_business(BusinessId(business_id), limit=limit)
            return [
                {
                    "when": row.recorded_at.isoformat(),
                    "event": row.event_type,
                    "actor": row.actor,
                    "payload": row.payload,
                    "cost_usd": float(row.cost_usd) if row.cost_usd else None,
                }
                for row in rows
            ]

    async def _kpi_series_readings(
        svc: KernelServices, contract: BusinessContract, *, limit: int
    ) -> list[dict[str, Any]]:
        """Per-metric observation history for the trend drill-down (M9-2a).

        design 13-company-workspace.md reserves a trend indicator until "a
        per-company KPI series read" exists — this is that read. One entry
        per contract `kpi_target`, mirroring `_goal_readings`' label fallback
        (a target's raw `key` never reaches the operator, spec §12.5) and
        reusing `KpiEngine.series` exactly as `_goal_readings` reuses
        `KpiEngine.latest`: no new query, no engine change.

        `points` is always present, oldest-first (`series` already orders it
        that way), even when empty — a target with no observation yet reads
        as "no points", the same empty-vs-null distinction `_goal_readings`'
        `measured: None` protects one level up, here kept as an empty list
        rather than a null so a client draws "no line yet" without a
        null-point special case.
        """
        engine = KpiEngine(svc.session)
        out: list[dict[str, Any]] = []
        for target in contract.kpi_targets:
            rows = await engine.series(contract.business_id, target.key, limit=limit)
            out.append(
                {
                    "label": target.operator_label or target.key.replace("_", " ").capitalize(),
                    "unit": target.unit,
                    "direction": target.direction.value,
                    "target": float(target.target_value),
                    "points": [
                        {"when": row.recorded_at.isoformat(), "value": float(row.value)}
                        for row in rows
                    ],
                }
            )
        return out

    @app.get("/api/companies/{business_id}/kpi-series")
    async def kpi_series(  # pyright: ignore[reportUnusedFunction]
        business_id: str, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Per-company KPI observation history (M9-2a).

        The read `design 13-company-workspace.md` reserves the trend element
        on: no route served `kpi_values`, so no line could be drawn through
        more than the single latest reading the goals drill-down already
        shows. `limit` is bounded rather than trusted, the same defensive
        shape `full_details`' own `limit` lacks and this route does not
        repeat — an unbounded value here would reach `KpiEngine.series`'s SQL
        `LIMIT` unchecked.
        """
        bounded_limit = max(1, min(limit, MAX_KPI_SERIES_LIMIT))
        async with kernel.services() as svc:
            try:
                rows = await svc.registry.list_instances()
                next(r for r in rows if r.business_id == business_id)
            except StopIteration:
                raise HTTPException(404, "No company with that id.") from None

            contract = await svc.registry.get_contract(BusinessId(business_id))
            return await _kpi_series_readings(svc, contract, limit=bounded_limit)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def dashboard() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """Serve the operator dashboard."""
        return FileResponse(f"{STATIC_DIR}/index.html")

    return app


__all__ = ["create_app"]
