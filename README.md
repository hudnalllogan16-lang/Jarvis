# Jarvis — AI Enterprise Operating System

Implementation of the **Jarvis Architecture Specification v1.4**, which is the single source of
truth. Where v1.4 left a mechanism unspecified, the choice is recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md) rather than made silently in code. Nothing in this
repository amends the specification.

**Current state: Milestone 5 — Affiliate Business, running as one application.**

`uv run python -m jarvis` opens Jarvis like a desktop app: every backend part starts and is
supervised behind the scenes (crashes restart with backoff and show as "restarting" in-app),
subsystems toggle in Settings, and with the `desktop` extra the dashboard is a native window
whose close button quits the app.

**Picking up development?** [`KICKOFF.md`](KICKOFF.md) has the session prompt to paste;
[`HANDOFF.md`](HANDOFF.md) has current state, what is and isn't verified, and the next work packets.

Just want to *use* Jarvis? [`GETTING_STARTED.md`](GETTING_STARTED.md) is the plain-language guide.

Roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md) · Dependency graph: [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md) · Delegation model: [`docs/DELEGATION.md`](docs/DELEGATION.md)

---

## What Milestone 4 adds

| Component | Spec | Module |
|---|---|---|
| Business Manager workflow | §2.1, D-004/5/6 | `jarvis/manager/workflow.py` |
| Manager activities | §2.1, D-004 | `jarvis/manager/activities.py` |
| Bounded durable state | §2.1, D-005 | `jarvis/manager/state.py` |
| Scheduler (§9 timers, §2.1 wakes) | §9, §2.1, D-012 | `jarvis/scheduler/service.py` |
| Capability contention gate | §2.2, A-004 | `jarvis/capabilities/contention.py` |

The Manager is generic — it contains no business-specific logic, which is what makes M5's
Affiliate Business a real test of §4's "configuration only" requirement.

## What Milestone 3 added

| Component | Spec | Module |
|---|---|---|
| Approval subsystem + autonomy ladder | §8 | `jarvis/approvals/service.py` |
| 24h re-notification, 7d auto-pause | §9 | same |
| Plain-language rendering | §8, §12.5, D-011 | `jarvis/approvals/rendering.py` |
| Notifications | §5, §9 | `jarvis/notifications/service.py` |
| KPI engine + Health Score | §5, §3, D-009 | `jarvis/kpi/engine.py` |
| Operator HTTP API | §1, §12.5 | `jarvis/api/app.py` |
| Dashboard (Sims-style card view) | §12.5 | `jarvis/api/static/index.html` |

Start it with `uv run python -m jarvis.api.server`, then open <http://localhost:8000>.

Nothing calls the 24h/7d timers on a schedule yet — that needs the scheduler, which arrives with
the Business Manager in M4. The timers are correct but dormant.

## What Milestone 2 added

| Component | Spec | Module |
|---|---|---|
| Event bus + per-consumer dedup | §2, A-002 | `jarvis/events/bus.py` |
| Budget ledger (4-level hierarchy) | §2.1/§2.2/§5/§9, D-003 | `jarvis/budget/ledger.py` |
| Platform circuit breaker | §9, §12.5 | `jarvis/budget/breaker.py` |
| Capability pool dispatch | §2.2, §9, D-001/D-002 | `jarvis/capabilities/pool.py` |
| Stateless execution shell | §6, §2.2 | `jarvis/capabilities/executor.py` |
| Scoped request / terminal result | §2.2, D-001 | `jarvis/capabilities/request.py` |
| Idempotency | §6, A-001 | `jarvis/capabilities/idempotency.py` |
| Contention policy (WFQ + floor) | §2.2, A-004 | `jarvis/capabilities/queue.py` |
| Credential resolution boundary | §10 | `jarvis/security/credentials.py` |
| Temporal activity boundary | §2, D-004 | `jarvis/runtime/activities.py` |
| Worker entrypoint | §2 | `jarvis/runtime/worker.py` |

Two of these — `CredentialManager` and `FairQueue` — are built and tested but have **no
production caller yet**, because nothing executes tools and dispatch is still synchronous. See
`docs/DECISIONS.md` for why they were built now anyway. Do not read them as live.

## What Milestone 1 delivered

| Component | Spec | Module |
|---|---|---|
| Platform Kernel container | §0 | `jarvis/kernel/container.py` |
| Business Registry | §0.1 | `jarvis/registry/registry.py` |
| Business lifecycle state machine | §0.1, D-008 | `jarvis/domain/lifecycle.py` |
| Standard Business Contract | §5 | `jarvis/domain/contract.py` |
| Audit Log | §11 | `jarvis/observability/audit.py` |
| Decision Log | §11.5 | `jarvis/observability/decision_log.py` |
| Scope authorization boundary | §10, D-002 | `BusinessRegistry.authorize_invocation` |
| Configuration & secrets handling | §0, §10 | `jarvis/kernel/config.py` |
| Secret-redacting structured logging | §10 | `jarvis/kernel/logging.py` |
| Provider-agnostic LLM interface | Directive, A-005 | `jarvis/llm/` |
| Schema migration | — | `migrations/versions/0001_kernel_foundation.py` |

## Still outstanding from §13 Step 1

- Finance Tracking Business (§13 Step 3) → M6, including the Manager's first live Temporal run
- Executive Layer (§3) → after two business types exist, per §13 Step 4

---

## Design notes worth knowing before reading the code

**Identity is derived, never declared.** `authorize_invocation` takes both the workflow's
registered business id and the id the request claims, and rejects any mismatch. Spec §10 requires
isolation to hold "including bugs or malformed requests", which is only achievable if the
requester is not the authority on its own scope.

**Scope violations are never narrowed.** A request asking for more than it may have is rejected
and audited, not silently trimmed. Trimming would hide the defect that produced it.

**Two logs, two audiences.** The Decision Log (§11.5) is not a filtered view of the Audit Log.
It has its own table, its own writer, and a write-time check that an entry actually explains
something. `record_platform_decision` exists so circuit-breaker trips and capital reallocation —
decisions belonging to no single business — still owe the operator a "why".

**Effects are returned, not performed.** `validate_transition` and `Registry.transition` return a
`TransitionEffects` describing what must happen (cancel timers, drain, block dispatch, revoke
credentials). The Registry stays bookkeeping infrastructure, per §0.1.

**No model identifier appears anywhere in the source.** Provider and model are configuration.
Seven supported vendors, three transports (A-005).

---

## Startup

Full walkthrough with troubleshooting: [`SETUP.md`](SETUP.md). Short version — requires
Python 3.14+, `uv`, and Docker.

```bash
git clone <repo> && cd jarvis
cp .env.example .env          # set JARVIS_LLM__MODEL and JARVIS_LLM__API_KEY
uv sync --all-extras

docker compose up -d          # postgres, redis, temporal, temporal-ui
uv run alembic upgrade head
```

Temporal UI: <http://localhost:8233>. Nothing schedules work yet — Milestone 1 has no workflows.

## Verification

```bash
uv run pytest -q                       # full suite
uv run pytest -q tests/test_registry.py # §0.1 registry + §10 isolation boundary
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run alembic upgrade head && uv run alembic downgrade base   # migration round-trips
```

Kernel smoke check:

```bash
uv run python -c "
import asyncio
from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel

async def main():
    kernel = PlatformKernel(Settings())
    async with kernel.services() as svc:
        print('installed types:', await svc.registry.installed_types())
    await kernel.aclose()

asyncio.run(main())
"
```

Two suites are dependency-free and can be run without any services running, which is useful as a
first check on a clean machine:

```bash
uv run pytest -q tests/test_lifecycle.py tests/test_logging_redaction.py \
                tests/test_fair_queue.py tests/test_runtime_identity_boundary.py
```

### Expected coverage of the isolation boundary

`tests/test_registry.py` asserts, among others, that a request cannot assert another business's
identity, cannot escalate tool or credential scope, cannot invoke an unpermitted capability, and
cannot dispatch to a paused company. These are the §10 guarantees; if one of them fails, stop and
flag it rather than adjusting the test.

---

## Repository layout

```
jarvis/
  kernel/         config, logging, errors, ids, runtime identity, DI container
  domain/         business contract, lifecycle state machine    (§5, §0.1)
  registry/       business registry + authorization anchor      (§0.1, §10)
  observability/  audit log, decision log                       (§11, §11.5)
  events/         event bus with per-consumer dedup             (§2, A-002)
  budget/         hierarchical ledger, circuit breaker          (§9, D-003)
  capabilities/   scoped requests, pool, executor, queue, idempotency (§2.2, §6)
  security/       credential resolution boundary                (§10)
  runtime/        Temporal activities and worker                (§2, D-004)
  llm/            provider-agnostic interface and transports
  persistence/    ORM models, engine, sessions
migrations/       alembic (0001 kernel, 0002 execution spine)
docs/DECISIONS.md implementation decision record
docs/ROADMAP.md    milestone sequence
docs/DEPENDENCIES.md dependency graph + layering invariant
tests/
```

## Conflict handling

Per §12, an instruction that would require violating a MUST or MUST NOT is **flagged, not
silently resolved**. If you find code in this repository that contradicts v1.4, the specification
wins and the code is the defect.
