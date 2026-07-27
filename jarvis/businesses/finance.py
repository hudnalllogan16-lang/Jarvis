"""The Finance Tracking Business type (spec §13 Step 3).

The second business type, and the packet that actually tests D-014's claim
(M7-1): if this module needs anything beyond values over
`BusinessTypeDefinition`, D-014 was wrong in a way only a second type could
show. Like `affiliate.py`, this module contains **no logic** — no class, no
function, no branch (asserted by tests/test_finance_type.py against the AST).

Per the owner-approved M7 scope, Finance Tracking reads operator-configured
metrics and public data via the Research capability only — it does not read
other businesses' ledgers or memory, and it does not act. Read-only per spec
§13 Step 3: no execution capability. Recommendation and execution live in the
Trading Analysis (§13 Step 5) and Live Trading (§13 Step 7) types today; the
owner's approved rule 3 contemplates this type evolving instead, which is a
§12 spec amendment the owner makes when that milestone arrives — not something
this file may anticipate (DECISIONS.md "M7 owner decision").

Because nothing here is ever proposable or approvable, `declared_action_types`
is empty by construction (zero `autonomy_policies`): M6-2's D-013 validation
then guarantees any model-proposed action degrades to no-action, recorded,
rather than executing anything.
"""

from __future__ import annotations

from decimal import Decimal

from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.domain.contract import CapabilityPermission, CapabilityType, KpiDirection, KpiTarget
from jarvis.domain.kpi import KpiMapping, KpiSource

FINANCE = BusinessTypeDefinition(
    name="finance_tracking",
    # 1.0.0 -> 1.0.1 for the KPI mappings; 1.0.1 -> 1.0.2 for
    # `data_freshness_hours` declaring its direction (M7-F30); 1.0.2 -> 1.0.3
    # for the D-027 amendment pass (M8-5, M7-F33/F49): `reports_delivered`
    # scoped to the finance capability's own results, `metrics_tracked`'s
    # target corrected to the type's real target count. Same reasoning each
    # time: `ensure_builtin_types` is version-gated (M6-F22, M7-F4:
    # `install()` refuses a duplicate version and the caller compares), so a
    # definition change that does not bump the version never reaches the live
    # Registry — it would keep serving the stale one. Minor, not major: A-003
    # resets graduation counters on a major bump, and nothing about
    # measurement changes what this type may do, let alone what it has earned
    # the right to do unattended.
    version="1.0.3",
    display_name="Finance tracker",
    # Present tense, not "never": the owner rejected permanently encoding that
    # this type will not recommend trades (DECISIONS.md "M7 owner decision"),
    # and this string is the operator-facing blurb on the "New company" card —
    # the most visible place a permanent promise could be made by accident.
    # It says what this company does today, which is the true and useful thing.
    description=(
        "Tracks the financial metrics you configure against public data and "
        "reports what changed. It reads and reports only: it places no trades "
        "and moves no money."
    ),
    prompt_templates={
        "finance_tracking.research": (
            "Gather public data relevant to the metrics this company tracks. "
            "Intent: {intent}\n"
            "Return, for each configured metric: the current public figure or "
            "benchmark, its source, and whether it has changed since the last "
            "check. Observation only — do not suggest any action."
        ),
        "finance_tracking.finance": (
            "Analyse the configured metrics using the research gathered. "
            "Intent: {intent}\n"
            "For each metric, report: its current value, how it compares to "
            "the operator's target, and the trend since the last report. Mark "
            "any figure that could not be verified as unverified rather than "
            "estimating it. This is a report for the operator to read, not a "
            "recommendation to buy, sell, or trade anything."
        ),
    },
    capability_permissions=(
        CapabilityPermission(
            capability=CapabilityType.RESEARCH,
            tool_scope=frozenset({"web_search"}),
            memory_read=True,
            max_invocation_budget_usd=Decimal("0.20"),
        ),
        CapabilityPermission(
            capability=CapabilityType.FINANCE,
            memory_read=True,
            memory_write=True,
            max_invocation_budget_usd=Decimal("0.30"),
        ),
    ),
    # No autonomy_policies: nothing this type does is ever proposable, so
    # declared_action_types (derived from autonomy_policies) is empty and no
    # action can graduate or need approval — there is none to gate.
    autonomy_policies=(),
    default_kpi_targets=(
        KpiTarget(
            key="metrics_tracked",
            operator_label="Metrics tracked",
            # 3, matching the three targets below — not a free-standing choice.
            # `metrics_tracked` maps to `CONFIGURED_KPI_TARGET_COUNT` below, so
            # `ProvisioningService.create_company` overwrites this at company
            # creation with the real count it derives from this very tuple
            # (`jarvis.domain.kpi.provisioned_kpi_targets`, M7-F49). Written as
            # 3 here rather than left at the old hand-picked 5, so a reader of
            # this file sees the number that will actually ship rather than one
            # the platform silently replaces — the old 5 was a structural 60%
            # cap no company could ever clear, because a type with three
            # targets can never carry more than three.
            target_value=Decimal("3"),
            unit="metrics",
        ),
        KpiTarget(
            key="data_freshness_hours",
            operator_label="Data freshness",
            target_value=Decimal("24"),
            unit="hours since last check",
            direction=KpiDirection.BELOW,
        ),
        KpiTarget(
            key="reports_delivered",
            operator_label="Reports delivered",
            target_value=Decimal("4"),
            unit="reports/month",
        ),
    ),
    # D-027.2 — what each of the targets above is measured from. Every source
    # is a fact the platform already records, so nothing here can be authored
    # by a model (D-011's reasoning, applied to numbers instead of prose, and
    # the mechanism behind compliance rule 4's "cite its source"). The keys
    # match `default_kpi_targets` above, which is what lets attainment compare
    # an observation with the goal it belongs to.
    #
    # The three targets are fully mapped; nothing about this type is left
    # unmeasured. `data_freshness_hours` is the one whose direction runs the
    # other way — lower is better — which is why its target above declares
    # `direction=KpiDirection.BELOW`: an excellent (low) freshness reading now
    # scores as attainment instead of a miss (M7-F30, fixed).
    kpi_mappings=(
        # `capability=FINANCE`: a cycle gathers data with Research and then
        # analyses it with Finance (both `prompt_templates` above), so an
        # unscoped count would score two succeeded results — one per
        # capability — for the one report the cycle actually delivered
        # (M7-F33). Finance is the capability whose output *is* the report;
        # Research's success is a step toward it, not a second one.
        KpiMapping(
            key="reports_delivered",
            source=KpiSource.SUCCEEDED_RESULTS_IN_CYCLE,
            capability=CapabilityType.FINANCE,
        ),
        KpiMapping(
            key="data_freshness_hours",
            source=KpiSource.HOURS_SINCE_NEWEST_SUCCEEDED_RESULT,
        ),
        KpiMapping(key="metrics_tracked", source=KpiSource.CONFIGURED_KPI_TARGET_COUNT),
    ),
    # Owner-approved 2026-07-26, verbatim (DECISIONS.md "M7 owner decision";
    # packet M7-3 Part 0). These replace the M7-1 draft, which stated the
    # restrictions as permanent properties of the type. The owner's revision
    # scopes them to M7 and explicitly rejects encoding "Finance will never
    # recommend trades" — the long-term roadmap includes recommendation,
    # brokerage management, and execution. Rule 3's condition ("once the
    # architecture explicitly enables those capabilities") is the operative
    # gate: enabling any of that is a §12 spec amendment owned by the owner,
    # not something a packet may infer from this approval.
    #
    # These are also now read at runtime, not only stored: `plan_cycle` puts
    # them in the planning prompt verbatim (D-027.5, closing M7-F22). They are
    # stored owner-approved values, so quoting them is D-011's direction, not
    # against it — the model is told the rules, never asked to restate them.
    compliance_requirements=(
        "During M7, Finance operates in observation-only mode. It may collect "
        "data, calculate KPIs, evaluate portfolio health, and produce research "
        "reports.",
        "During M7, Finance must not place orders, modify orders, transfer "
        "funds, or perform any brokerage write operations.",
        "Finance may evolve in later milestones to generate trade "
        "recommendations, risk assessments, and eventually execute trades "
        "through approved brokerage integrations once the architecture "
        "explicitly enables those capabilities.",
        "Every reported figure must either cite its source, originate from an "
        "approved brokerage or market-data provider, or be clearly marked as "
        "estimated or unavailable.",
        "Finance may only access data that it is explicitly authorized to "
        "access by the architecture and business-isolation rules.",
        "Reports generated during M7 are informational only and do not "
        "constitute financial, investment, legal, or tax advice.",
        "The owner approves these compliance requirements for the M7 launch.",
    ),
    suggested_budget_usd=Decimal("15.00"),
    suggested_wake_ceiling_usd=Decimal("0.60"),
    schedule_cron="0 9 * * *",
    # Schedule-based only (owner-approved M7 scope). No event_triggers: nothing
    # here is ever approvable, so no approval.decided (D-006 still holds
    # platform-wide; this type simply never raises one). KPI_THRESHOLD_BREACHED
    # exists and is published (jarvis/kpi/engine.py) and would be a plausible
    # future wake condition for a metrics-tracking business, but wiring it is
    # outside this packet's owner-approved scope, not a gap in this file.
    event_triggers=frozenset(),
    # No tool_registry entry: no effect-performing tool is granted to any
    # capability here (only RESEARCH's non-effect web_search scope), so there
    # is nothing for the approved-action path (D-015) to look up.
    tool_registry={},
)
