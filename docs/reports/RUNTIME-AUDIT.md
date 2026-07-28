# Runtime Orchestration Audit — startup to autonomous operation

**Commissioned by the owner. Design/audit only — nothing in this lane changes behaviour.**
Branch `lane/runtime-audit`, cut from main `cfc374c` (M9 merged, M10 next).

Scope: trace the path from application launch to autonomous operation and answer six
questions with code evidence; classify every gap under the owner's four categories;
recommend an implementation plan without implementing it.

**Live evidence caveat.** `docker compose ps` returned no containers on the audit host, so
Postgres and Temporal were not reachable and no live DB or Temporal read was performed. No
worker was started (per the lane's terms), $0 spent, no `.env` contents printed, no ports
bound beyond an in-process ASGI app construction. Every claim below is traced in source or
demonstrated by an in-process check; where a claim would need the live system to confirm, it
is marked as such. No port conflicts were observed because nothing was bound.

---

## 1. Startup trace summary

There are **three composition roots**, and they do not compose the same runtime. This is the
single most important fact in the audit: "did Jarvis start?" has three different answers
depending on which command was run, and two of the three produce a system that never acts on
its own.

### Topology A — the launcher (`python -m jarvis`, console script `jarvis`)

`jarvis/__main__.py:3-5` imports and calls `jarvis.shell.launcher:main`. `pyproject.toml:19-20`
declares exactly one console script, `jarvis = "jarvis.shell.launcher:main"` — there is no
`jarvis-worker` or `jarvis-api` entry point, so the other two topologies are reachable only as
`python -m ...` module invocations.

`launcher.py::launch` (172-245) runs, in order:

1. `Settings()` + `PlatformKernel(settings)` (186-187).
2. `run_preflight(kernel)` (189) — three checks only: database, Temporal, LLM config
   (`preflight.py:187-190`).
3. If it cannot serve, `_try_start_services()` runs `docker compose up -d` and re-checks for
   up to ~2 minutes (190-198).
4. Hard stop if the database is unreachable (207-212).
5. `_apply_migrations()` — `alembic upgrade head` in-process (214).
6. `await kernel.ensure_builtin_types()` (215).
7. `Supervisor()` with **four parts** (218-222):
   - `api` / "Dashboard" → `_serve_api` (99-128)
   - `worker` / "Company runner" → `_run_worker_when_possible` (131-141)
   - `scheduler` / "Timers and reminders" → `_run_scheduler` (144-148)
   - `executive` / "Budget and health checks" → `_run_executive` (151-155)
8. Waits for the port to bind, opens a window or browser, then blocks on
   `supervisor.run_until_stopped()` (237-241).

Each part is restarted with doubling backoff capped at 60s, and the crash count resets after
30s of stability (`supervisor.py:27-29, 104-137`). This is the only topology with supervision.

### Topology B — the worker (`python -m jarvis.runtime.worker`)

`worker.py::main` (197-204): build kernel → `ensure_builtin_types()` → `asyncio.gather(run_worker,
run_scheduler, run_executive)`. Same three autonomy parts as the launcher, **minus the API and
minus supervision**. SETUP.md:338 labels this "prod topology".

### Topology C — api-only (`python -m jarvis.api.server`)

`api/server.py::_run` (14-35): build kernel → `ensure_builtin_types()` → `uvicorn.serve`. **No
worker, no scheduler, no executive.** The dashboard renders, companies can be created and
marked ACTIVE, and nothing will ever run them. Nothing in this path warns about that.

### What actually produces autonomy

Autonomy requires three separate loops, and only Topologies A and B start any of them:

| Loop | Started by | Function | Cadence |
|---|---|---|---|
| Temporal worker | `run_worker` (`worker.py:38-101`) | polls `jarvis-platform` queue, hosts `BusinessManagerWorkflow` + all activities | continuous |
| Scheduler sweep | `run_scheduler` (`worker.py:104-136`) | §9 timers, reservation reconcile, **Manager auto-start**, event dispatch | 300s, hardcoded |
| Executive tick | `run_executive` (`worker.py:139-194`) | rollup → census → cap alerts → halt narrative (D-041) | `Settings.executive.tick_interval_seconds`, default 60s |

The chain that turns an ACTIVE company into a running Manager is:

`run_scheduler` → `Scheduler.sweep()` (`scheduler/service.py:91-118`) → line 109
`ManagerLifecycle(self._kernel).reconcile()` → `lifecycle.py:42-86` → for each ACTIVE instance,
`client.start_workflow("BusinessManager", ..., id=f"bm-{business_id}")`.

`run_scheduler`'s loop calls `sweep()` **before** its first `asyncio.sleep` (`worker.py:116-136`),
so under Topologies A and B a Manager for an already-ACTIVE company starts within seconds of
boot, not 300s later. That part is correct.

### Which topology gives autonomy

| Capability | A: launcher | B: worker | C: api-only |
|---|---|---|---|
| Migrations applied | yes (`launcher.py:214`) | no | no |
| Builtin **types** installed | yes (`launcher.py:215`) | yes (`worker.py:200`) | yes (`server.py:28`) |
| Dashboard / operator API | yes | **no** | yes |
| Temporal worker polling | yes | yes | **no** |
| Manager auto-start (`reconcile`) | yes | yes | **no** |
| §9 approval timers | yes | yes | **no** |
| Event dispatch → Manager wakes | yes | yes | **no** |
| Executive tick (D-041) | yes | yes | **no** |
| Crash supervision + restart | yes (`supervisor.py`) | **no** (`asyncio.gather`) | n/a |
| Survives without a GUI session | **no** (`launcher.py:312-327`) | yes | yes |

**The operator is expected to run Topology A.** INCIDENT-M9-F118:32-33 states it directly — "the
launcher IS the supervised topology; ad-hoc lane workers are dev artifacts" — and
GETTING_STARTED.md:39/51 is written to match. But the bottom row is the unresolved problem: the
only fully supervised topology is also the only one that cannot run unattended, because its
lifetime is bound to a desktop window. No row in this table describes a supported way to run
Jarvis autonomously and indefinitely. That is M10-F7.

---

## 2. Answers to the six questions

### Q1 — Which runtime components initialize at startup?

**Topology-dependent.** Under the launcher: Settings, PlatformKernel, preflight, Alembic
migrations, builtin business *types*, then four supervised parts (`launcher.py:186-222`). Under
the worker: kernel, builtin types, and the three autonomy loops (`worker.py:197-204`). Under
api-only: kernel, builtin types, uvicorn — and nothing else (`api/server.py:26-33`).

`CapabilityPool` is **not** a startup singleton. It is constructed per unit of work by
`PlatformKernel.build_pool(services)` (`kernel/container.py:239-248`), bound to a request-scoped
session. See Q4.

### Q2 — Are Manager processes instantiated?

**Yes, and automatically — but only where a scheduler runs, and only via one call path.**

`ManagerLifecycle.reconcile` has exactly **one** production caller: `Scheduler.sweep`,
`scheduler/service.py:109`. A repo-wide search for `ManagerLifecycle` / `.reconcile` returns that
line, the import at `service.py:34`, the class definition at `lifecycle.py:33`, and two test files
(`tests/test_manager_start_state.py:122`, `tests/test_reservation_reconcile.py:77-78`). Nothing else.

So: an ACTIVE company's Manager **is** auto-started at boot under Topologies A and B, on the
first sweep, within seconds. Under Topology C it is never started at all.

Exactly-one is enforced by Temporal workflow-id collision (`lifecycle.py:11-13, 88-109`) rather than
a check-then-start race, and reconcile drains the `business.activated` backlog each pass
(`lifecycle.py:62`) while treating the Registry as the authority. That design is sound.

Two structural consequences:

- Manager auto-start is **coupled to the scheduler part's liveness**. If `scheduler` is the part
  that crashes, the launcher restarts it and the next sweep repairs everything — fine. But in
  Topology B `asyncio.gather` has no supervision, so a scheduler exception ends the process.
- `reconcile` returns `0` silently when Temporal is unreachable (`lifecycle.py:54-56`), and so does
  `dispatch_events` (`service.py:316-318`). See M10-F9.

### Q3 — Are businesses automatically registered and activated?

**Types yes; companies no. The distinction is real and verified.**

`ensure_builtin_types` (`kernel/container.py:423-500+`) iterates `self._builtin_types`, compares
installed version against definition version, and calls `provisioning.install(definition)` for
anything absent or upgraded. `install()` registers a **business type** — a template. It creates no
company instance.

Company creation is a separate, operator-driven call: `ProvisioningService.create_company`
builds a `BusinessContract`, calls `register_instance`, then transitions to
`LifecycleState.ACTIVE` and publishes `BUSINESS_ACTIVATED`
(`businesses/provisioning.py:290-330`). Its only production caller is the HTTP route
`POST /api/companies` (`api/app.py:574-599`), i.e. the dashboard's "Create and start" button.

So a fresh install reaches "autonomous operation" with **zero companies** and correctly does
nothing. Autonomy begins when an operator creates the first company. This matches
GETTING_STARTED.md:61 ("Give it a name and a monthly budget, then **Create and start**") and is
intended behaviour, not a gap.

### Q4 — Does the dispatch engine exist, and is it enabled?

**It exists and is enabled. There is no kill switch and no disabled flag.**

`CapabilityPool` (`capabilities/pool.py:61-91`) is fully wired: session, registry, ledger,
breaker, executor, audit, idempotency, contention gate, event bus. A search for `enabled` across
`jarvis/capabilities/*.py` returns **no matches** — there is no pool-level enable/disable
setting. Dispatch is gated per-business by the contract's `capability_permissions`, the
contention gate (§2.2, A-004), and the budget hierarchy — not by a global toggle.

The "subsystem toggle" surface (`api/app.py:856-891`) is easy to mistake for one. It is not: it
toggles a **business type's** visibility on the "New company" card via
`registry.set_type_enabled`, and its docstring is explicit that existing companies keep their own
running/paused state (`app.py:878-881`). Turning a subsystem off cannot stop an autonomous company.

Event dispatch is likewise live: `Scheduler.dispatch_events` (`service.py:306-349`) claims each
ACTIVE business's subscribed event types and signals its Manager (`wake` or `approval_decided`).
It runs on every sweep (`service.py:110`).

### Q5 — Is autonomous work scheduling implemented or deferred?

**Implemented — but at a materially weaker fidelity than the contract vocabulary implies.**

The Manager parks on its own Temporal timer rather than being polled: `_await_wake`
(`manager/workflow.py:516-528`) does `workflow.wait_condition(..., timeout=timedelta(seconds=
ctx.schedule_interval_seconds))`, so a schedule wake and a signal wake race, and the signal cuts
the wait short. Cycles run in `run` (`workflow.py:250-375`) and continue-as-new after
`CYCLES_BEFORE_CONTINUATION` (369-375). This is real, durable, autonomous scheduling.

The fidelity problem is the translation. `_interval_seconds` (`manager/activities.py:1919-1936`):

```python
minute, hour = fields[0], fields[1]
if hour == "*":
    return 3600
if minute.isdigit() and hour.isdigit():
    return 86400
return 3600
```

`schedule_cron="0 9 * * *"` — used by both shipped types (`businesses/affiliate.py:116`,
`businesses/finance.py:190`) and the default in `businesses/definition.py:78` — becomes a flat
**86400-second interval**, not a 9am wall-clock cron. The wake anchors to whenever that Manager
last parked and drifts from there. `domain/contract.py:181` describes the field as "Cron
expression for schedule-based waking, e.g. a daily planning cycle", which overstates what runs.

This directly corroborates INCIDENT-M9-F118's finding that the three wakes "had fired
independently 7.5–20 hours earlier" and that the apparent synchrony was "a worker-outage
artifact... Not synchronized scheduling; a recovery burst." Three Managers on independently
anchored 24h timers is exactly the spread the incident measured. The incident called this a
supervision problem rather than a scheduling one; the supervision half is right, and the drift
is a second, still-open half.

The v1 subset is a deliberate, documented §14 scope choice (`activities.py:1921-1925`). It becomes
a genuine defect only when a business type needs wall-clock alignment — which M10 (Trading
Analysis) does, because market hours are not negotiable.

### Q6 — Does behaviour match the intended architecture?

**Mostly yes at the component level; no at the topology and documentation level.**

Matches: one Manager per business enforced by workflow id (§2.1); the scheduler kept out of the
workflow layer as deterministic bookkeeping (§2.1/§3, D-012, `service.py:14-18`); the Executive
tick as a plain asyncio timer rather than a workflow (D-041, `worker.py:139-155`); contained
failure in both loops (`worker.py:134-135, 192-193`); the launcher documented as a third
composition root that holds no logic (`launcher.py:14-18`).

Does not match:

1. **The intended topology is not the documented one.** INCIDENT-M9-F118:32-33 records the
   deferred posture as "the launcher IS the supervised topology; ad-hoc lane workers are dev
   artifacts". GETTING_STARTED.md:39 agrees — `uv run python -m jarvis`, and line 51: "You don't
   need to start anything else, ever." But README.md:49 tells the reader to start Jarvis with
   `uv run python -m jarvis.api.server` (README.md:49), and SETUP.md:338 labels `python -m jarvis.runtime.worker`
   the "prod topology". Three documents, three different intended topologies, and the one the
   README leads with is the only one with zero autonomy. See M10-F3.

2. **The launcher's own health reporting does not work.** See M10-F1 — verified, not inferred.

3. **A partial topology fails silently rather than loudly**, which contradicts the degradation
   philosophy stated in `launcher.py:20-26`. See M10-F2.

---

## 3. Gap classification

The owner asked whether missing autonomous business management is (1) an implementation gap,
(2) a disabled feature, (3) a startup sequencing issue, or (4) a milestone planning oversight.

**It is not (2).** Nothing is disabled. There is no flag, setting, or toggle anywhere in the tree
that switches autonomy off. The subsystem toggles govern template visibility only
(`app.py:875-891`), and `CapabilityPool` has no enablement concept at all.

**It is not primarily (3) either**, and this is the audit's central correction to the framing.
Sequencing inside each topology is correct: migrations precede type installation, type
installation precedes serving, and the scheduler sweeps once before its first sleep so Managers
start at boot rather than 300s in. Nothing is ordered wrongly.

**The dominant classification is (4), with (1) close behind.**

| Category | Findings | Weight |
|---|---|---|
| (1) Implementation gap | M10-F4, F5, F7, F9 | Substantial — real missing code, none of it large |
| (2) Disabled feature | none | Nil |
| (3) Startup sequencing | M10-F6 (coupling, not ordering) | Minor |
| (4) Milestone planning oversight | M10-F1, F2, F3, F8 | Dominant |

The oversight is specific and nameable: **nine milestones built autonomy without ever
designating a supported way to run it unattended.** The launcher is an interactive desktop
application whose lifetime is tied to a window (`launcher.py:312-327`); the worker topology has
no supervision; the api-only topology has no autonomy. There is no service, daemon, unit file,
restart policy, or documented long-running posture anywhere in the repository. M9-F118's seven-to-
twenty-hour unserved wakes were the predictable outcome, and the incident correctly deferred it
with an owner rather than closing it.

---

## 4. Recommended plan

Recommendations only. Separated as the owner asked: what M10 genuinely needs, what is one line,
what is documentation, and what is missing code.

### 4.1 One-line changes

- **Scheduler interval to Settings (M10-F5).** Add `SchedulerSettings.sweep_interval_seconds`
  (default 300) beside `ExecutiveSettings.tick_interval_seconds` and read it in `run_scheduler`
  exactly as `run_executive` already does (`worker.py:175-179`). `config.py:134` already names this
  gap in prose. Roughly a five-line change including the settings class.

### 4.2 Documentation (no code)

- **Designate one supported autonomous topology and say so once (M10-F3).** Fix README.md's
  "Current state: Milestone 5" header and its line 49 instruction to launch api-only; retire
  SETUP.md's "Can't: run a company autonomously. There is no Business Manager and no scheduler"
  (line 320) and its "prod topology" label on line 338. GETTING_STARTED.md is already correct and
  should be the model. This is stale-doc cleanup, not new writing.
- Correct `domain/contract.py:181`'s description of `schedule_cron` to state the supported subset,
  or fix the code (4.4) and leave the prose.

### 4.3 What M10 actually needs — a persistent autonomous posture

This is the real deliverable and it is a design question, not a patch. M10 is Trading Analysis
(`docs/ROADMAP.md`, milestone 10, Next). A trading business that only reasons while a desktop
window happens to be open is not a trading business.

Recommended shape, for owner decision rather than immediate build:

1. **A headless supervised entrypoint.** Today supervision (`shell/supervisor.py`) is only
   reachable through the desktop launcher. Extract the supervised composition — worker, scheduler,
   executive, optionally api — behind a `jarvis-run` console script that never opens a window and
   never exits on window close. This is a re-composition of existing parts, not new runtime logic,
   and keeps `launcher.py`'s "this file holds no logic" property intact.
2. **An OS-level restart policy.** A Windows Service / systemd unit / container with
   `restart: unless-stopped`. In-process supervision cannot survive process death, which is the
   failure mode M9-F118 actually hit.
3. **A liveness signal the operator can see.** Worker-poller staleness surfaced as a health
   component, so "no worker has polled for N minutes" is visible rather than inferred from
   Temporal's UI after the fact.
4. **Wall-clock scheduling** (4.4, M10-F4) — a hard prerequisite for market hours.

Items 1 and 2 close M9-F118's deferred supervision posture. Item 3 closes the silence.

### 4.4 Genuinely missing code

- **M10-F1 — the shadowed health route.** Delete the launcher's duplicate registration and pass
  the Supervisor into `create_app`, or have the launcher mutate the existing route's dependency.
  Small, but it restores the operator-visible signal three other mechanisms assume exists.
- **M10-F2 — silent partial topology.** `api/server.py` should log once at startup, and report as
  a health component, that no worker/scheduler/executive is running in this process. It need not
  refuse to start; it must stop implying autonomy.
- **M10-F4 — real cron.** Replace `_interval_seconds` with wall-clock next-fire computation. Note
  this changes Manager wake behaviour and therefore requires the `workflow.patched()` versioning
  convention (`workflow.py:93-160` shows the established pattern) — it is not a free edit.
- **M10-F9 — sweep observability.** Log at INFO once per sweep when Temporal is unreachable, and
  count `managers_started` in `run_scheduler`'s trigger condition.

### 4.5 Suggested sequencing

M10-F5 and the doc corrections first (cheap, unblock nothing but remove active misdirection);
M10-F1 and M10-F2 next (restore visibility before adding load); then the 4.3 posture design as an
owner-gated packet; M10-F4 last, as a versioned workflow change inside M10's own trading work.

---

## 5. Findings

### M10-F1 — The launcher's parts-aware `/api/health` is permanently shadowed (category 4)

`create_app` registers `/api/health` at `api/app.py:1015`. The launcher then registers a **second**
route at the same path at `launcher.py:103-125`, intending to add Supervisor part statuses.
Starlette matches routes in registration order, first match wins, so `create_app`'s route always
serves and the launcher's is dead code.

Verified in-process, not inferred — building the app and appending a second `/api/health` the way
the launcher does yields two routes, and the first match resolves to
`create_app.<locals>.health`, never the launcher's.

Consequences: `parts` is always `[]` under **every** topology; `api/static/app/system.js:83`
(`(await get('/api/health').catch(() => ({ parts: [] }))).parts || []`) therefore renders an empty
part list in Settings forever; and `run_worker`'s docstring claim that a rejected model "shows the
operator 'Company runner — restarting' with a crash count in the health banner"
(`worker.py:47-53`) is false as shipped. The launcher also loses `run_preflight`'s report in favour
of `app.py`'s hand-maintained duplicate checks — which `app.py:1030-1039` admits are "kept in sync
by hand".

Root cause is a fix-induced regression: M6-5a added the route to `create_app` to stop the
standalone dashboard 404ing, and in doing so shadowed the richer one. `tests/test_api_health_route.py`
asserts `body["parts"] == []` (line 60) and documents the launcher's route as "richer" without ever
asserting it is served — which is why this survived to M9.

### M10-F2 — The api-only topology is silently non-autonomous (category 4 + 1)

`api/server.py:14-35` starts no worker, no scheduler, no executive. A company created through this
process reaches `LifecycleState.ACTIVE`, publishes `BUSINESS_ACTIVATED`, appears "running" on the
dashboard (`app.py:411`), and will never wake. The `/api/health` route reports Temporal as reachable
whenever the container is up (`app.py:1060-1074`) — Temporal being *reachable* says nothing about
whether anything is *polling* it, which is precisely the distinction M9-F118 turned on.

This contradicts the launcher's stated degradation philosophy (`launcher.py:20-26`), where every
missing dependency produces a banner in operator language. A missing *topology* produces nothing.

### M10-F3 — Operator-facing docs disagree about which topology to run, and two are stale (category 4)

- README.md:8 — "**Current state: Milestone 5**". The repo is at M9 merged.
- README.md:49 — "Start it with `uv run python -m jarvis.api.server`" — the zero-autonomy topology.
- README.md:51-52 — "Nothing calls the 24h/7d timers on a schedule yet... The timers are correct but
  dormant." Untrue since M4.
- README.md:135 — "Nothing schedules work yet — Milestone 1 has no workflows."
- SETUP.md:230 — "companies arrive in Milestone 4"; SETUP.md:249-250 — the worker "will sit idle".
- SETUP.md:320-321 — "**Can't:** run a company autonomously. There is no Business Manager and no
  scheduler, so nothing wakes up on its own."
- SETUP.md:338 — `python -m jarvis.runtime.worker  # worker + scheduler only (prod topology)`.

GETTING_STARTED.md:39 and :51 are the only correct operator instructions in the repository. An
operator following README or SETUP gets either no autonomy or an unsupervised process.

### M10-F4 — `schedule_cron` is flattened to a drifting fixed interval (category 1)

`manager/activities.py:1919-1936` reduces any five-field cron to 3600 or 86400 seconds. Both shipped
business types use `"0 9 * * *"` (`affiliate.py:116`, `finance.py:190`) and therefore wake every
86400 seconds from wherever their Manager last parked — never at 09:00. `domain/contract.py:181`
describes the field as a cron expression. Corroborated by INCIDENT-M9-F118:11-14's 7.5–20 hour
spread across three Managers. Blocking for M10's market-hours requirement.

### M10-F5 — Scheduler sweep interval is hardcoded and un-configurable (category 1, one line)

`worker.py:104` — `async def run_scheduler(kernel, *, interval_seconds: int = 300)`. No caller
overrides it: `launcher.py:148` and `worker.py:202` both pass only the kernel. `ExecutiveSettings`
has `tick_interval_seconds` (`config.py:130`) and its own docstring at `config.py:134` names the
asymmetry — "the scheduler's `interval_seconds` (300s, un-configured today)". This is M9-F92,
already known, still open, and genuinely one settings field plus one lookup.

### M10-F6 — Manager auto-start is coupled to the scheduler part's liveness (category 3)

`ManagerLifecycle.reconcile` has exactly one production caller, `scheduler/service.py:109`. Manager
recovery is therefore a side effect of the timer sweep rather than an independently supervised
concern. Under the launcher this self-heals (the supervisor restarts `scheduler` and the next sweep
repairs state), so the risk is contained. Under Topology B it does not: `asyncio.gather`
(`worker.py:202`) has no supervision, so an unhandled scheduler exception ends the whole process,
taking the worker and executive with it. Sequencing within a topology is correct; the coupling
across topologies is not.

### M10-F7 — No persistent autonomous posture exists anywhere in the repository (category 1 + 4)

No service definition, unit file, restart policy, or headless entrypoint. `pyproject.toml:19-20`
declares one console script and it opens a desktop window. `launcher.py:312-327` ties the process
lifetime to that window: `stop.set()` on close, `services.join(timeout=15)`, exit. Supervision
exists but is reachable only through the GUI path. This is the deferred item INCIDENT-M9-F118:31-33
recorded as "worker-supervision posture", and it is the gap M10 must close before a trading
business can be trusted to run unattended.

### M10-F8 — Business types are auto-installed; companies are never auto-created (category 4, informational)

Verified as the owner asked. `ensure_builtin_types` (`container.py:423+`) installs **types** only, via
`provisioning.install(definition)`. Company instances come solely from
`ProvisioningService.create_company` (`provisioning.py:290-330`), whose only production caller is
`POST /api/companies` (`app.py:574-599`). Types registered ≠ companies created — confirmed. This is
correct and intended behaviour; it is recorded here because "no company is running" on a fresh
install is easily misread as an autonomy failure when it is an empty-state.

### M10-F9 — A Temporal outage makes the sweep a silent no-op (category 1)

`ManagerLifecycle.reconcile` returns `0` when `temporal_client()` is `None`
(`lifecycle.py:54-56`); `Scheduler.dispatch_events` does the same (`service.py:316-318`). Neither
logs. `run_scheduler` only logs when `report.renotified or report.expired or report.woken or
report.reservations_released` is truthy (`worker.py:119`) — and `managers_started` is **not** in that
condition, so a sweep whose only work was starting Managers logs nothing either. A scheduler running
against an unreachable Temporal produces an indefinite silent stream of zero-work sweeps. This is
the same silence family as M9-F118 and reachable under the launcher, not only under partial
topologies.

---

## Verification

Gates run on this lane: docs-only change, expected exit 0. No merge, no push, no `DECISIONS.md`
edit, no live worker started, no live DB or Temporal read (services were down), $0 spent.
