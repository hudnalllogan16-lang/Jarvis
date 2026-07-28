# The Operational Runtime

**Status:** design, awaiting Manager review. Packet M10-P0 (Phase 0, Operational Readiness),
lane `lane/m10-p0`, cut from `m9-baseline` (947757a). **No implementation.**

**Scope:** how Jarvis runs unattended. The headless supervised entrypoint; the worker topology
and what supervises it; restart policy; liveness and readiness; the supported deployment modes;
autonomous recovery; wall-clock scheduling; and the validation that closes Phase 0. Trading
Intelligence is gated on this document's packets landing and its Part 8 evidence being produced.

**Founding inputs, treated as authoritative:** `docs/reports/RUNTIME-AUDIT.md` (the
three-topology finding and its plan separation), `docs/reports/M9-RATIFICATION-REVIEW.md` P7
(the boundary test — a finding is M10's if fixing it changes how Jarvis is *deployed,
supervised, or scheduled in wall-clock time*), and `docs/reports/INCIDENT-M9-F118.md` (the
outage shape). M10-F1 is fixed and closed; **F2, F4, F5, F6, F7 and F9 are this document's to
design against.** Nothing here decides anything D-001…D-053 already decided.

**Live evidence.** Unlike the audit and the ratification review, both of which ran against a
stopped stack, the infrastructure was **up** for this lane and was read **read-only**: Temporal
via `DescribeTaskQueue`, `ListWorkflowExecutions` and history fetches; Postgres via a single
`SELECT` over `business_instances`. No worker was started, nothing was written, no port was
bound, no unowned process was touched, $0 was spent, no `.env` contents were read or printed.
The four `jarvis-*` containers were already running and were left running.

---

## Part 0 — What the live platform is doing right now

Every argument in this document rests on one measurement, taken at **2026-07-28 19:45 UTC**:

| Reading | Value |
|---|---|
| `DescribeTaskQueue("jarvis-platform")`, workflow pollers | **0** |
| `DescribeTaskQueue("jarvis-platform")`, activity pollers | **0** |
| Infrastructure uptime (postgres, redis, temporal, temporal-ui) | **2 days** |
| ACTIVE companies in `business_instances` | **3** |
| RUNNING `BusinessManager` executions | **3** |
| Last history event on each | `TIMER_STARTED`, **13.5 hours ago** |

Three companies are parked on wake timers. Nothing has polled the queue those wakes will land
on for thirteen and a half hours, against a database and a workflow runtime that have both been
healthy for two days. **M9-F118 is not a past incident. It is the platform's current state**, and
it is invisible: `/api/health` would report the workflow runtime **reachable**, because it is.

One execution's history makes the second half of the problem exact. `bm-biz_0812…` declares
`schedule_cron = "0 9 * * *"` in its stored contract:

```
event 156  TIMER_STARTED   2026-07-26 22:40:31   start_to_fire = 1 day, 0:00:00
event 157  TIMER_FIRED     2026-07-27 22:40:31
event 158  WORKFLOW_TASK_SCHEDULED …            (unserved)
event 173  WORKFLOW_TASK_STARTED  2026-07-28 06:14:53   ← 7h34m after the wake fired
event 181  TIMER_STARTED   2026-07-28 06:14:54   start_to_fire = 1 day, 0:00:00
```

Three separate facts, all measured rather than inferred:

1. The timer is **86400 seconds**, not 09:00. The contract says nine in the morning; the code
   flattens that to "a day from whenever you last parked" (`manager/activities.py::_interval_seconds`).
2. The wake **fired on time and was served 7h34m late**, because nothing was polling — the same
   7.5-to-20-hour spread INCIDENT-M9-F118 measured, reproduced independently in a different
   execution a day later.
3. The new timer **re-anchored to 06:14:54**. The outage did not delay one cycle; it *moved the
   schedule*. This company's "daily 9am planning cycle" now runs at 06:14, and the next outage
   will move it again. Nobody chose 06:14. Nobody can see that it happened.

That is the whole of Phase 0 in one history: **nothing keeps the runtime alive, nothing says when
it stops, and the schedule quietly rewrites itself every time it does.**

---

## Part 1 — The topology decision

### 1.1 The finding, restated as a design constraint

The audit's central fact is that there are three composition roots which do not compose the same
runtime. The instinct is to fix the roots. That is the wrong target: three roots is fine — the
layering test already names them and they are how the object graph gets built. **The defect is
that each root writes its own part list.** The part list is the topology, it exists three times,
and nothing in the repository asserts the three agree. They do not agree, and the disagreement is
invisible until an operator runs the wrong one.

So the constraint this design accepts is narrower and stronger than "unify the entrypoints":

> **The set of supervised parts is written down exactly once. Every entrypoint is a choice of
> which face to put on that one set, never a second opinion about what the set is.**

`Supervisor.add` is called from exactly one module today (`launcher.py:218-221`) and nothing
enforces it (**M10-F19**). Making that a test is the mechanical guard against the whole family.

### 1.2 The shape: one supervised core, four faces

    jarvis/shell/service.py          ← the ONLY part table; a fourth composition root
      bootstrap(settings)            preflight → (wait|refuse) → migrations → builtin types
      build_supervisor(kernel, *, with_api)   the four parts, in one place, once
      serve_headless()               signals, exit codes, no window, no browser, ever

    jarvis-run          → service.serve_headless()                    the platform
    jarvis              → service.bootstrap + build_supervisor + a window    the console
    python -m jarvis.api.server  → console-only attach; declares itself     read surfaces
    (deleted) python -m jarvis.runtime.worker                         no longer a topology

**`jarvis-run` is the platform.** A new console script in `pyproject.toml`, alongside `jarvis`.
It composes `api`, `worker`, `scheduler` and `executive` under the existing `Supervisor`
(D-017), never imports `jarvis.shell.desktop`, never opens a browser, and has no window whose
close event can end it. It is the entrypoint every deployment mode in Part 6 actually runs.

**`jarvis` becomes the operator console.** It calls the same `bootstrap` and the same
`build_supervisor`, and adds exactly one thing: a window. This preserves D-016's development
experience unchanged — one command, everything running — while making the desktop application
structurally incapable of being a *different* runtime from the service. The owner's criterion
("the desktop application becomes an operator console rather than the platform itself") is met
in the strong sense: in Modes 1 and 2 the console **attaches** to a runtime it did not start and
whose lifetime it cannot end. In Mode 3 it still hosts one, for development.

**Topology B is deleted, not fixed.** `runtime/worker.py::main` and its `__main__` block go.
`run_worker`, `run_scheduler` and `run_executive` stay exactly as they are — they are the parts,
and they are good. What goes is the bare `asyncio.gather` that ran them without supervision and
which SETUP.md called "prod topology". This is the cheapest possible answer to M10-F6: the
coupling the audit describes is a property of the *unsupervised* topology, and the topology is
the thing being removed. `worker.py` keeps its composition-root exemption, re-justified in its
docstring: it is where the Executive tick is composed (D-041), not where a process is defined.

**Topology C stays, and starts telling the truth (M10-F2).** `python -m jarvis.api.server` is a
legitimate mode — a console attached to a runtime running elsewhere is exactly Mode 1's operator
surface. What was wrong was silence. The fix is *not* "this process logs that it has no worker",
because that only helps the person who started this process. The fix is Part 3's: **every
topology reports whether a supervised runtime is alive anywhere, because the answer lives in
shared state rather than in the process serving the page.** A console that cannot see a runtime
says so, whether the runtime is missing, dead, or on another host.

### 1.3 Layering and the composition-root rule

`jarvis/shell/service.py` joins `COMPOSITION_ROOTS` in `tests/test_layering.py`. It is a
composition root by the same definition as the other four: it constructs the object graph and
holds no logic. `test_composition_roots_hold_no_logic` applies to it unchanged.

One new test, and it is the load-bearing one:

**`test_one_part_table`** — an AST scan asserting that `Supervisor.add` is called from exactly
one module in `jarvis/`. A fifth entrypoint may exist; a second opinion about what runs may not.
This is the gate that would have caught the three-topology divergence at the commit that created
it, and it is three lines of AST walking.

### 1.4 Bootstrap: the one behaviour the console and the service must not share

`bootstrap()` is shared. Its response to a missing dependency is not (**M10-F15**).

`launcher.py:206-211` refuses to start when the database is unreachable, and for an interactive
command that is right: a developer who typed a command is present to read the message and fix it.
A **service** that exits because it started three seconds before Postgres is a service that has
outsourced a dependency-ordering problem to its restarter, and every subsequent symptom will be
reported as "the restart loop".

So `bootstrap(settings, *, on_unavailable)` takes the posture as a parameter:

| Posture | Used by | Behaviour when the database is unreachable |
|---|---|---|
| `REFUSE` | `jarvis` (console) | print the ladder, exit — today's behaviour, unchanged |
| `WAIT` | `jarvis-run` (service) | retry preflight every 5s indefinitely; log at INFO on the first failure and every 60s thereafter; write a heartbeat row (Part 3) in state `waiting` so the console can say what it is waiting for |

The service never gives up on a dependency that may still be starting. It gives up only on
configuration that cannot become valid (Part 2.4's exit code 3).

`bootstrap` also fixes **M10-F10**: `launcher.py:74` tests `Path("docker-compose.yml")` and
`launcher.py:96` builds `Config("alembic.ini")` — both relative to the process working directory.
A Windows service does not inherit a useful cwd. `bootstrap` resolves the installation root
explicitly (from `__file__`, overridable by `JARVIS_HOME`) and passes absolute paths, so
migrations cannot silently target nothing. NSSM's `AppDirectory` would mask this; the code must
not depend on it being set.

`_try_start_services()` — `docker compose up -d` — is **console-only**. A service running as
LocalSystem should not be starting a Docker Desktop that belongs to a user session (Part 6.1,
**M10-F11**).

---

## Part 2 — Restart policy

### 2.1 Two tiers, with a boundary neither crosses

| Tier | Restarts | Mechanism | Owns |
|---|---|---|---|
| 1 | a **part** | `jarvis/shell/supervisor.py` (D-017) | crash → log → backoff 1s…60s → restart; reset after 30s stable |
| 2 | a **process** | the operating system (Part 6) | unexpected exit → throttled restart, forever |

The boundary is absolute in both directions. **Tier 1 never attempts process resurrection** — an
in-process supervisor cannot survive its own process death, which is precisely the failure mode
M9-F118 hit and the reason D-017's supervision was necessary but not sufficient. **Tier 2 never
reasons about parts** — it sees a process, an exit code, and a throttle window, and that is all
it should ever see. The moment an OS-level restarter starts having opinions about which part
crashed, there are two supervisors disagreeing about one system.

### 2.2 Why an unconditional restart is safe

Stated explicitly because a restart policy that is unsafe is worse than none, and this one is
safe for reasons that are properties of the existing architecture rather than promises:

- **The process holds no Manager state.** Every Manager is a Temporal workflow; its history is
  the state, and it is in Postgres. A worker that dies mid-cycle loses a workflow *task*, not a
  cycle — Temporal re-delivers it to the next poller. The 7h34m gap in Part 0 is the proof: the
  work was still there when a poller finally arrived.
- **The sweep is idempotent.** `Scheduler.sweep` re-notifies, expires, reconciles reservations,
  reconciles Managers and dispatches events from stored state each pass, and starting an
  already-running Manager is a no-op by workflow-id collision (`manager/lifecycle.py:11-13`).
- **`reconcile` is a repair, not an event handler.** Its docstring already says so. Whatever a
  restart missed, the next sweep fixes — and `run_scheduler` sweeps *before* its first sleep, so
  "the next sweep" is seconds after boot, not five minutes.
- **Migrations are idempotent** (`alembic upgrade head`) and already run on every launch.

There is exactly one restart hazard and it is not state: a process that restarts every two
seconds because its configuration is invalid produces a log the operator cannot read and a
Temporal namespace churning connections. That is what the throttle and exit code 3 are for.

### 2.3 Exit codes are the interface between the tiers

| Code | Meaning | Tier 2 should |
|---|---|---|
| 0 | clean stop, operator-requested (service control, Ctrl-C, SIGTERM) | **not** restart |
| 2 | a dependency was unavailable past the waiting posture's own patience | restart, throttled |
| 3 | configuration cannot become valid (`Settings()` refused, root unresolvable) | restart, throttled, and the throttle *is* the alarm — an escalating gap is the visible signal |

D-053's posture is untouched: a rejected model id stops **the worker part**, not the process, and
the read surfaces keep serving. That is a Tier-1 event and stays one.

### 2.4 Shutdown

`serve_headless` installs handlers for `SIGINT`, `SIGTERM` and — because Windows is the host of
record — `SIGBREAK`, all of which set the same stop event `launch()` already watches (D-017's
`threading.Event` seam, reused as-is). On stop: cancel every part, `await` the supervisor's own
cancellation path, write a final heartbeat row in state `stopped` so the console can distinguish
**"stopped"** from **"vanished"**, then `kernel.aclose()`. A drain budget of 15 seconds matches
the launcher's existing `services.join(timeout=15)`.

That final heartbeat is not decoration. "The runtime stopped cleanly at 04:12" and "the runtime
was last seen at 04:12" are different operational facts and today the platform can express
neither.

---

## Part 3 — Liveness and readiness

### 3.1 The distinction the incident turned on

`check_temporal` (`shell/preflight.py:138-160`) asks whether the workflow runtime is **reachable**
and reports OK when it is. In Part 0's live reading it would report OK. It has been reporting OK
throughout thirteen and a half hours of nothing happening.

> **Reachable is not served.** A queue with zero pollers is perfectly reachable.

Every liveness mechanism below exists to make that distinction visible without an operator having
to open Temporal's UI and reason about `WFT_TIMEDOUT` events after the fact — which is the
forensic exercise M9-F118's report had to perform and **M10-F18**'s gap: nothing in the repository
records that a runtime existed, which parts it ran, or when it last spoke.

### 3.2 Two signals, neither trusted alone

**Signal 1 — the runtime heartbeat (self-report).** A new `runtime_heartbeat` table, one row per
`(runtime_id, part_name)`:

    runtime_id      uuid, generated at process start
    part_name       'api' | 'worker' | 'scheduler' | 'executive' | 'runtime'
    hostname, pid
    started_at, last_beat_at
    state           supervisor PartState, plus 'waiting' and 'stopped'
    consecutive_crashes, last_error

The Supervisor upserts every `heartbeat_interval_seconds` (default 15). One small write per part
per interval; the row is bounded and never grows.

*Why a table and not a file or Redis.* The console may be a different process on a different host
(Modes 1 and 2), so the signal must live somewhere every mode already shares. Postgres is the one
dependency without which nothing runs at all (`HealthReport.can_serve`). Redis is present but is
not load-bearing and its absence degrades rather than stops the platform — a liveness fact that
disappears when a non-critical dependency blinks is a liveness fact that will be disbelieved.

**Signal 2 — poller staleness (external report).** `DescribeTaskQueue` on
`settings.temporal.task_queue` for both the workflow and activity queue types, returning the
poller count and the newest `last_access_time`. This is the check that produced Part 0's `0`, and
it is independent of anything the runtime says about itself.

**Why both.** They fail in opposite directions and each covers the other's blind spot:

| Failure | Heartbeat says | Pollers say |
|---|---|---|
| process killed | stale | zero |
| worker part wedged inside a poll that never returns | **RUNNING — a lie** | stale `last_access_time` |
| scheduler or executive part dead, worker fine | stale for that part | **healthy — blind** |
| Temporal down, runtime healthy | all parts fine | unavailable, and correctly not "zero" |

A single-signal design gets two of those four wrong. Note the last row: an unreachable Temporal
must render as *unknown*, never as *zero pollers* — "we cannot tell" and "nothing is listening"
are different sentences and conflating them manufactures the false alarm that trains operators to
ignore the real one.

### 3.3 Where the facts live, and where the verdict lives

This is constrained rather than chosen, and the constraint is worth recording (**M10-F17**).

D-038 confines `jarvis/executive` to importing `registry`, `budget`, `kpi`, `observability` and
`notifications` — so the layer that raises every other platform-level alert **cannot** import
`jarvis.runtime` or `jarvis.kernel` to ask whether a worker is polling. The resolution:

- **Facts → `jarvis/observability/heartbeat.py`** (milestone 1). A `HeartbeatStore` that writes
  beats and reads them back, plus the pure `assess_runtime_liveness(beats, pollers, now,
  thresholds) -> RuntimeLiveness`. Writers: the Supervisor (shell, M5 → M1, legal). Readers: the
  API health route (M3 → M1, legal) and the Executive (M9 → M1, legal by D-038's own list).
- **Probe → injected, never imported.** The Temporal poller probe is built by the composition
  root and handed to the Executive tick as a value, exactly as `platform_ceiling_usd` already is
  (`runtime/worker.py:190`). The Executive receives a reading, not a dependency.
- **Verdict → `jarvis/executive/liveness.py`**, an L1 rule (Part 7.1) that notifies on
  transition, in the same shape as `raise_spend_alerts`.

A future packet that "just imports `jarvis.runtime` from the executive" breaks D-038. It is
recorded here so that is a knowing act rather than an accident.

### 3.4 Readiness is a different question (M10-F16)

`/api/health` is a narrative surface. By D-016's degradation ladder it always answers 200 with a
body describing what is degraded and what to do — which is exactly what a container healthcheck
or a service throttle must **not** consume, because to them 200 means "send traffic".

Add **`/api/ready`**: no narrative, no components, 200 or 503.

    200  database reachable AND schema at head AND builtin types installed
         AND (if this process runs parts) every part in RUNNING
    503  otherwise, with a one-line reason

Rule: **readiness gates, health explains, and one endpoint never does both.** `/api/ready` is what
Mode 2's healthcheck polls and what Mode 1's install script waits on; `/api/health` stays the
operator's page and gains two components:

| Component | Source | States |
|---|---|---|
| `runtime` | heartbeat rows | ok / degraded (a part restarting or one part stale) / down (no fresh beat from any runtime) / stopped |
| `workers` | `DescribeTaskQueue` | ok (≥1 poller, fresh) / degraded (pollers present, `last_access_time` stale) / down (zero pollers) / unknown (Temporal unreachable) |

Both render under every topology, including api-only — which is how M10-F2 closes.

### 3.5 What the operator sees

Illustrative only; §12.5 copy is `operator-surface-engineer`'s and this design does not ratify
wording. The point is the *shape*: a duration and a consequence, never a mechanism.

> **Nothing has been running your companies for 13 hours.** Three companies are waiting to work.
> Start Jarvis's background service, and they will pick up where they left off.

Compare with what the platform says today about the same state: *"Companies can run."*

---

## Part 4 — Scheduling correctness

### 4.1 What is actually wrong

`_interval_seconds` (`manager/activities.py:1919-1936`) reduces any five-field cron to 3600 or
86400. Part 0 measures the consequence on a live execution and the ratification review measured
the sharper edge independently: `'0 9,16 * * *'` — a legitimate twice-daily schedule — becomes
**hourly**, a 12× billable over-fire bounded only by `max_cycles_per_day = 48`.

Two distinct defects, and both must be fixed together or the fix is cosmetic:

1. **The interval is not the schedule.** `"0 9 * * *"` means 09:00, not "every 24 hours".
2. **The anchor is the last park, so every outage moves it.** Part 0's execution drifted
   22:40 → 06:14 in a single incident and will keep drifting. A wall-clock schedule that is
   re-anchored by an outage is not a schedule; it is an interval wearing a cron's clothes.

Fixing only (1) — computing a correct next-fire from a drifted anchor — still drifts. Fixing only
(2) does not exist. Wall-clock computation *is* the anti-drift property: the next fire is derived
from the calendar, so an outage delays one cycle and the schedule is unmoved.

### 4.2 The mechanism

`_interval_seconds(cron) -> int | None` is replaced by `next_fire_at(cron, tz, after) -> datetime
| None`, computed **in the activity** and returned as an absolute UTC instant on `CycleContext`:

    load_cycle_context  →  next_fire_at_utc: datetime | None      (replaces schedule_interval_seconds)
    _await_wake         →  delay = max(next_fire_at_utc - workflow.now(), MINIMUM_PARK)

The activity computes it because the workflow may not read a clock (D-004) and because `zoneinfo`
resolution is file-backed I/O that has no business inside the workflow sandbox. `workflow.now()`
is replay-safe, and the activity's result is recorded in history, so the delay is deterministic on
replay by construction.

`MINIMUM_PARK` (60s) covers the case where a cycle overruns its own next fire: the Manager parks
briefly and the next context load recomputes against the calendar. An early wake is harmless — it
is gated by `max_cycles_per_day` and the wake-cycle ceiling, both already enforcing — whereas a
negative timeout is a crash.

A **pure, tested cron parser** lands with this, supporting the standard five fields including
lists (`9,16`), ranges (`1-5`), steps (`*/15`) and their combinations. This is not speculative
scope under §14: `'0 9,16 * * *'` is a schedule the platform already accepts and already
mis-executes, and M10's market hours are not negotiable. An expression the parser cannot express
is **refused at contract validation**, loudly, rather than silently flattened — the flattening is
the whole defect.

### 4.3 Timezone

`WakeConditions.schedule_timezone`, default `"UTC"`, IANA names only, validated at contract
creation. UTC is the platform's clock of record and every stored instant is already UTC.

Governance thread, stated because market hours will pull on it: a business **type** may *request*
a timezone in its definition (`Origin.TYPE_DEFINITION` — a request, per the plugin trichotomy,
8.3), and only the owner's creation or refresh flow *establishes* one (`Origin.OWNER` /
`APPROVED_CONFIG`). A type declaring `America/New_York` for market hours is asking, not deciding.

### 4.4 A missed wake is skipped, not replayed

The rule, stated as narrowly as it can be:

> **A schedule period admits at most one cycle.** A wake served before its period ends runs, with
> its lateness recorded. A wake still unserved when the next fire time passes is **skipped**, and
> the skip is announced.

Worked through Part 0's execution: the wake fired 22:40 on the 27th and was served 06:14 on the
28th — still inside the daily period, so it runs, stamped 7h34m late. Had the runtime been down
until 23:00 on the 28th, the next fire would already have passed: skip, one notice, re-park.

*Why not replay.* A worker down thirteen hours must never restart into thirteen hours of backlog:
each cycle is billable, `max_cycles_per_day = 48` bounds the burst at forty-eight rather than
preventing it, and the *content* of a missed 09:00 planning cycle is worthless at 22:00 — the
planner would work to a day that has ended. Silence is worse: silently draining a backlog is
precisely the "recovery burst" INCIDENT-M9-F118 had to reconstruct after the fact and mistook for
synchronized scheduling.

*Rejected alternative:* a `missed_wake_grace_seconds` parameter. It introduces an ENFORCING value
(it decides whether a billable cycle runs) to answer a question the cron expression already
answers exactly. The period is the grace window.

**`wake_lateness_seconds` is recorded on every cycle decision**, not only late ones. A field that
appears only when something is wrong cannot be trended, and "wakes have been getting later for a
week" is the signal that precedes an outage rather than following it.

### 4.5 D-033: this is a versioned workflow change

`PATCH_WALL_CLOCK_SCHEDULE = "wall-clock-schedule"`, one module constant in
`manager/workflow.py`, following the established convention exactly
(`tests/test_workflow_versioning.py`).

**One patch id, not two**, guarding both the new park computation and the `record_late_wake`
command. They are one behavioural change; splitting them would allow a history to take the new
timer and the old silence, which is a state neither version was designed for.

Unlike `PATCH_PAUSED_WAKE_NOTICE` and `PATCH_NOTHING_TO_DO_KPIS`, whose branches no committed
fixture ever reached, **both fixtures park on timers** — this patch's old path is genuinely
exercised by them, so "the fixtures still replay unedited" is real evidence here rather than a
vacuous pass. Both must replay, and the scripted pair (the same loop driven with the version
decision open and closed) still ships alongside.

Three RUNNING executions are parked on the old path **right now**. They must survive the deploy
untouched, and the whole point of D-033 is that they do.

### 4.6 The sweep interval (M10-F5 / M9-F92)

`SchedulerSettings.sweep_interval_seconds`, default 300, beside `ExecutiveSettings.tick_interval_seconds`,
read in `run_scheduler` exactly as `run_executive` already reads its own. Five lines, known since
M9, and it arrives here rather than as a drive-by because **it also registers** (Part 7.2) — a
cadence that governs when approvals expire is a parameter, and adding it without a register row
would create the next M9-F130 row on the day it shipped.

---

## Part 5 — Autonomous recovery

### 5.1 The ladder

| Level | Failure | Recovery | Latency |
|---|---|---|---|
| Task | a workflow task lost mid-flight | Temporal re-delivers to the next poller | seconds |
| Activity | a bounded failure | `STANDARD_RETRY`, then D-001's terminal result | seconds |
| Part | a supervised coroutine raised | Supervisor: backoff 1s…60s, restart | 1–60s |
| Process | the process died | OS restarter (Part 6), throttled | throttle window |
| Host | reboot | service starts at boot; `bootstrap` in `WAIT` posture | boot + dependencies |
| State | anything the above missed | `Scheduler.sweep` → `reconcile` on the next pass | ≤ sweep interval |

Every level exists today except **Process** and **Host**, which is exactly the audit's finding.

### 5.2 Sweep observability (M10-F9)

`ManagerLifecycle.reconcile` and `Scheduler.dispatch_events` both return `0` and log nothing when
the Temporal client is `None`. Three changes, all small:

1. **Log on transition, not per sweep.** The `Scheduler` instance remembers whether Temporal was
   reachable last pass and logs at WARNING when that changes, in both directions. A thirteen-hour
   outage should produce two lines and a health component, not 156 identical lines — a log that
   repeats itself is a log nobody reads, which is the same silence in a different costume.
2. **A liveness heartbeat every Nth sweep** (default 12, i.e. hourly at the default cadence) so a
   long outage is visibly *ongoing* rather than only *begun*.
3. **`managers_started` joins the log trigger** in `run_scheduler`, so a sweep whose only work was
   starting a Manager stops being silent.

### 5.3 Reconciliation stays inside the sweep (M10-F6)

The audit is right that Manager auto-start is coupled to the scheduler part's liveness, and right
that under the launcher this self-heals. With Topology B deleted (1.2), the unsupervised case that
made the coupling dangerous no longer exists.

**A fifth supervised part is deliberately not added.** The residual risk is narrower: one sweep
sub-step raising skips the sub-steps after it for that tick. That is a containment question, and
the containment fix is local — each sub-step of `Scheduler.sweep` gets its own `try/except`,
reporting per-step outcomes on `SweepReport`, so a failing renotify cannot stop reconciliation.
Adding a part would add a second Temporal client, a second failure surface and a second thing to
supervise, to solve a problem a `try` block solves.

### 5.4 The crash-loop honesty rule

Backoff caps at 60s and `consecutive_crashes` is already tracked. What is missing is a threshold
at which the platform stops implying it is coping. Design: at **10 consecutive crashes** of one
part — ten minutes of failure at the capped backoff — the part's health state becomes `failing`
rather than `restarting`, and a notification is raised once per condition (deduped exactly like
D-053's `UNFINISHED_ROUND`). A part that has been "restarting" for six hours is not restarting.

---

## Part 6 — Supported deployment modes

| # | Mode | Command | Restart | Console | Autonomy | Status |
|---|---|---|---|---|---|---|
| 1 | **Windows service** | `jarvis-run` under NSSM | NSSM, throttled | browser or the desktop app, attaching | full | **primary** |
| 2 | **Containers** | `jarvis-run` in compose | `restart: unless-stopped` | browser | full | supported |
| 3 | **Desktop console** | `jarvis` | Tier 1 only | native window | full **while open** | development + operator |
| 4 | **Console-only attach** | `python -m jarvis.api.server` | none | browser | **none, and it says so** | supported |

Four honest modes replacing three accidental topologies. Mode 4 is not a degraded Mode 1; it is a
read surface for a runtime hosted elsewhere, and Part 3's components make that legible.

### 6.1 Mode 1 — Windows, the host of record

**The choice: NSSM, with Task Scheduler documented as the no-download fallback.**

| Candidate | Verdict |
|---|---|
| **NSSM** | **Chosen.** A real service (starts at boot, no logged-in user required); restarts on *unexpected* exit only, so an operator-initiated stop stays stopped; `AppThrottle` gives a genuine throttle rather than a hot loop; `AppStdout`/`AppStderr` with rotation solve log capture, which is otherwise unsolved for a Windows service; `AppStopMethodConsole` delivers a console event the process can drain on. Cost: a vendored third-party binary — pin the version and record its SHA-256 in the deployment doc. |
| Task Scheduler | **Fallback.** Built in, no download, can run at boot as SYSTEM. But it restarts a *task* only on failure, treats exit 0 as success and stops, and has no usable stdout capture. Adequate; strictly worse. Documented for environments that forbid third-party binaries. |
| pywin32 in-process service | **Rejected.** Puts the restarter inside the thing being restarted — the exact structural error D-017's in-process supervisor already demonstrated the limits of. Also adds a Windows-only dependency and Windows-only code to a cross-platform tree. |
| `pythonw` + a Startup shortcut | **Rejected.** Session-bound. It fails the owner's criterion outright — it is the current problem with a different window manager. |

Service definition (values, not a script — the script is packet P0-F):

    Application         <venv>\Scripts\jarvis-run.exe
    AppDirectory        <install root>          # belt and braces; M10-F10 removes the dependency
    AppExit Default     Restart
    AppThrottle         60000                   # ms; below this counts as a failed start
    AppRestartDelay     5000
    AppStopMethodConsole 15000                  # matches the 15s drain budget
    AppStdout/AppStderr <install root>\logs\jarvis-run.log, rotate at 10MB, keep 10
    Start               SERVICE_AUTO_START (delayed)

**M10-F11 — the honest problem with Mode 1, and it needs an owner decision.** Docker Desktop on
Windows is a **per-user application**. A LocalSystem service starting at boot will find Postgres,
Redis and Temporal unreachable until a user logs in and Docker Desktop starts. `bootstrap`'s
`WAIT` posture makes that survivable rather than fatal — the service waits, says what it is
waiting for, and starts the moment the dependencies appear — but "survivable" is not
"unattended", because a host that reboots with nobody to log in never becomes autonomous.

Three answers, and the owner picks one:

1. **Auto-login + Docker Desktop at login.** Pragmatic, single-box, matches the current
   development host. Weakest security posture; a locked console is the mitigation.
2. **Postgres as a native Windows service and Temporal server as a second NSSM-wrapped binary.**
   Removes Docker from the runtime path entirely. Most robust; the largest operational change,
   and it makes the compose file a development-only artifact.
3. **A Linux or WSL2 host (Mode 2).** `restart: unless-stopped` under a real daemon makes all of
   this a non-question. Cheapest technically; changes the deployment story the owner has stated.

**Delayed auto-start is not a fix for this** — it buys ninety seconds against a dependency that
may take an hour, or forever. It is configured anyway because it is free.

### 6.2 Mode 2 — containers

`docker-compose.yml` has **no `restart:` policy at all**, confirmed against the running system:
`docker inspect` reports `RestartPolicy.Name=no` on every container. They have survived two days
only because nothing killed them (**M10-F14**).

- `restart: unless-stopped` on `postgres`, `redis`, `temporal` and `temporal-ui`.
- A new `jarvis` service running `jarvis-run`, `restart: unless-stopped`, `depends_on` the
  Postgres healthcheck, with its own healthcheck polling **`/api/ready`** (Part 3.4) — the reason
  that endpoint has to exist separately from `/api/health`, which would report 200 while
  reporting that nothing works.
- `JARVIS_HEADLESS=1` in its environment as a second belt: `jarvis-run` never opens a window, but
  the variable makes the intent explicit and is already honoured (`shell/desktop.py:44`).

### 6.3 Mode 3 — the desktop console

Unchanged in behaviour, changed in status. It remains the developer experience D-016 designed and
the operator's local console. It is no longer "the supported autonomous topology", because there
now is one.

When a runtime is already serving on `api_port` (Mode 1 or 2 on the same host), the console
should **attach** rather than compete for the port. Detection is already there:
`desktop.wait_for_dashboard` does a TCP connect. Probe first; if the port answers, open the window
onto the existing runtime and start no parts. That single behaviour is what makes "close the
window" a no-op for the platform — and it is the owner's headline criterion, testable in Part 8.

### 6.4 Documentation

README.md and SETUP.md were corrected at M9 closeout to name the launcher as the supported
autonomy topology. Those corrections become wrong the moment `jarvis-run` exists. A new
`docs/DEPLOYMENT.md` owns the mode matrix, the NSSM and Task Scheduler procedures, the M10-F11
decision as recorded by the owner, and the operational runbook; README/SETUP/GETTING_STARTED
point at it rather than restating it. **Three documents restating one topology is how M10-F3
happened**; the fix is one authority and three pointers.

---

## Part 7 — Governance

Spec v1.6 §15: any new executable action registers, and the Action Registry refuses unregistered
actions at import. Parameters register with legitimate origins.

### 7.1 Actions to register

| Action | Level | Approval | Audit | Module / symbol |
|---|---|---|---|---|
| `runtime.liveness_verdict` | **L1** | NONE | AUDIT, NOTIFY_ON_TRANSITION | `jarvis/executive/liveness.py::raise_runtime_liveness_alerts` |
| `business.late_wake_notice` | **L1** | NONE | AUDIT, NOTIFY_ON_TRANSITION | `jarvis/manager/activities.py::record_late_wake` |

Both are L1 by the level's own definition — the entire behaviour is a comparison of stored values
against owner-set parameters (beat age against `heartbeat_stale_after_seconds`; a wake's service
time against its own next fire), firing and announcing without asking. Both mirror an existing
entry exactly: `spending.platform_band_notice` for the first, `business.dropped_wake_notice`
(D-035) for the second. Neither invents governance vocabulary; each picks four values.

**One emit site each**, per the registry's unique-emit-site convention. `runtime.liveness_verdict`
consumes *both* Part 3.2 signals and produces one verdict rather than splitting into two
near-identical rows — the component that enforces the rule is the component that announces it
(design 1.6).

**Deliberately not registered, with the line drawn on purpose:**

- **Writing a heartbeat row.** A fact record, not an authority-bearing action — the audit log's
  own writes are likewise unregistered. Registering every write would make the registry a schema
  rather than a constitution.
- **Starting, stopping or restarting the process.** An operator starting a process, and an
  operating system restarting one, are both prior to the authority model rather than actions
  within it. The platform is not the actor.
- **Refusing to start on invalid configuration.** An exit is the absence of action. D-053 already
  governs the one refusal that *is* an action (the model check), and it stops a part, not a
  process.

`trading.*` remains unregistered and unwritten. This packet adds no L2, L3, L4 or L5 entry, and
`AUTONOMY_PIN` moves by exactly two rows.

### 7.2 Parameter register rows

| Name | Class | Origin | Source |
|---|---|---|---|
| `settings.scheduler.sweep_interval_seconds` | ANNOUNCING | APPROVED_CONFIG | Settings, owner-adjustable |
| `settings.runtime.heartbeat_interval_seconds` | ANNOUNCING | APPROVED_CONFIG | Settings, default 15 |
| `settings.runtime.heartbeat_stale_after_seconds` | ANNOUNCING | APPROVED_CONFIG | Settings, default 45 (3× the beat) |
| `settings.runtime.poller_stale_after_seconds` | ANNOUNCING | APPROVED_CONFIG | Settings, default 300 |
| `settings.runtime.part_failing_after_crashes` | ANNOUNCING | APPROVED_CONFIG | Settings, default 10 (5.4) |
| `wake_conditions.schedule_cron` | ANNOUNCING | PLATFORM_DEFAULT | code default `"0 9 * * *"` (`businesses/definition.py:78`) |
| `wake_conditions.schedule_timezone` | ANNOUNCING | PLATFORM_DEFAULT | code default `"UTC"` (new field) |

All ANNOUNCING under Part 2.1's effect test: each paces, warns or describes; none changes what
the platform may or may not do. The two PLATFORM_DEFAULT rows are recorded honestly rather than
dressed up — nobody authorised `"0 9 * * *"` or `"UTC"`, and for an ANNOUNCING parameter a
recordable origin is admissible. `schedule_cron` earns a row it does not have today precisely
because **this design changes what the value means**; a value whose semantics move must be
visible in the register on the day they move.

`wake_lateness_seconds` (4.4) is a recorded measurement, not a parameter. No row.

---

## Part 8 — Production runtime validation

The evidence that closes Phase 0 and unlocks Trading Intelligence. Each item maps to one of the
owner's criteria and produces an artifact, not an opinion.

| # | Test | Passes when |
|---|---|---|
| V1 | Install the service; **log the Windows session out entirely**; wait 10 minutes | `DescribeTaskQueue` ≥ 1 poller in both queue types; heartbeat fresh for all four parts; a cycle recorded with no session open |
| V2 | `taskkill /F` the runtime process | pollers return within the throttle window; the console afterwards shows the gap as a duration, with a start and an end |
| V3 | Reboot the host | autonomy resumes with no human action (or, under M10-F11 answer 1, after auto-login only) |
| V4 | Stop Temporal for 10 minutes | exactly **one** WARNING transition line plus hourly heartbeats; `workers` reads *unknown*, never *zero*; one recovery line; no crash loop; the runtime process never exits |
| V5 | Set a company to `*/5 * * * *`; observe three consecutive fires | each wake lands within **±30s** of the wall-clock boundary; the anchor does not move between fires |
| V6 | Park a Manager; stop the runtime past its next fire; restart | exactly **one** late-wake notice for that company; **zero** replayed cycles; lateness recorded |
| V7 | Open and close the desktop console twice while the service runs | poller count and heartbeat freshness unchanged throughout; **zero** effect on any company |

**V7 is the headline.** It is the owner's criterion stated as a measurement: the desktop
application is an operator console rather than the platform itself, and the way you know is that
closing it does nothing.

V1, V3 and V4 must be re-run under whichever M10-F11 answer the owner picks; the results are
different under each, and the deployment document records which one was measured.

---

## Part 9 — What this design does not do

**9.1 In-band alerting cannot report its own host's death.** In Mode 1 the API is a part of the
runtime, so if the process dies, nothing serves the console that would have shown the alert.
`runtime.liveness_verdict` therefore reports a *past* outage reliably and a *present* one only
when something else is still serving. The mitigations are out of band by nature — NSSM's stderr
log, the Windows Event Log, a future external notifier — and all of them are M10-later or M11.
Stated plainly here because a liveness design that does not name this limit is claiming a
guarantee it does not have. What this design *does* guarantee is that the outage is
impossible-to-miss **afterwards**, with a duration attached, which is strictly more than the
platform has today and is what M9-F118 lacked.

**9.2 No metrics or dashboards beyond `/api/health` and `/api/ready`.** No Prometheus, no
OpenTelemetry, no time-series. §14 forbids speculative scope and nothing here has demonstrated a
need the two endpoints plus the heartbeat table cannot serve.

**9.3 No multi-host or HA runtime.** One runtime instance is assumed. The heartbeat schema keys on
`runtime_id` and `hostname` so a second instance is *visible*, but nothing coordinates two, and
two schedulers sweeping the same database is untested. Single-runtime is an assumption, not a
guarantee — the schema records enough to detect a violation.

**9.4 No change to `reliability`'s blindness to FAILED cycles.** It is on the M10 metric-semantics
pass with M7-F60 and stays there.

**9.5 No secrets handling change.** `.env` and `Settings` are unchanged. The service's
environment carries no secret; `AppDirectory` plus `.env` is the whole mechanism, and the
deployment doc must say so rather than demonstrating `AppEnvironmentExtra` with a key in it.

**9.6 Escalations for the owner.** (a) **M10-F11** — the Windows unattended-dependency decision,
which gates V1/V3 and cannot be made by engineering. (b) Whether Mode 3 should remain able to
*host* a runtime at all, or be attach-only always: this design keeps hosting for development, and
making it attach-only is a one-line change if the owner prefers the stronger separation.

---

## Part 10 — Proposed decisions

Drafted for the Manager to write into `docs/DECISIONS.md` after review. **Not written here.**
Next free identifier is D-054 (D-053 is the highest recorded).

- **D-054 — Jarvis has one supervised runtime and one part table; the desktop application is a
  console that attaches to it, never the platform that hosts it.** `jarvis-run` is the supported
  unattended entrypoint; `jarvis` composes the same parts through the same builder and adds only a
  window; `python -m jarvis.api.server` is a console-only attach that declares the platform's
  runtime state from shared facts rather than from its own process. `Supervisor.add` is called
  from exactly one module, enforced by test. The unsupervised worker topology is deleted.
  *Reversal cost:* low — it is composition, and the parts are unchanged.
- **D-055 — restart is two-tier: a part is the Supervisor's, a process is the operating system's,
  and neither crosses.** The process holds no Manager state (Temporal does), the sweep is
  idempotent and `reconcile` repairs on the next pass, which is what makes an unconditional OS
  restart safe. Exit codes are the interface: 0 clean, 2 dependency-unavailable, 3
  configuration-refused. *Reversal cost:* low.
- **D-056 — Windows is the deployment host of record and `jarvis-run` runs there as a service
  under an external supervisor, never as a session-bound process.** NSSM chosen with a pinned
  version and recorded hash; Task Scheduler documented as the no-download fallback with its limits
  stated; an in-process pywin32 service wrapper rejected because it puts the restarter inside the
  thing being restarted. Containers with `restart: unless-stopped` are the second supported mode.
  *Reversal cost:* low — it is packaging, not architecture.
- **D-057 — reachable is not served; liveness is measured two ways and neither is trusted alone.**
  A `runtime_heartbeat` fact written by the Supervisor (self-report) and Temporal's own poller
  count (external report); an unreachable Temporal renders as *unknown*, never as *zero*. Facts
  live in `observability` so D-038 holds; the probe is injected by the composition root; the
  verdict is an L1 rule in the Executive that notifies on transition. *Reversal cost:* low.
- **D-058 — readiness and health are separate endpoints.** `/api/ready` is a gate (200/503, no
  narrative) for orchestrators and service throttles; `/api/health` remains the operator's
  narrative surface and always answers, per D-016's degradation ladder. One endpoint never does
  both. *Reversal cost:* none.
- **D-059 — `schedule_cron` means wall-clock cron, and a schedule period admits at most one
  cycle.** The next fire is computed as an absolute UTC instant by an activity and parked to by
  the workflow under `PATCH_WALL_CLOCK_SCHEDULE` (D-033); an expression the parser cannot express
  is refused at contract validation rather than flattened. A wake still unserved when its next
  fire passes is skipped with a notice, never replayed as a burst, and lateness is recorded on
  every cycle. An outage delays a cycle and no longer moves the schedule. *Reversal cost:* medium
  — a versioned workflow change with live executions parked on the old path.
- **D-060 — the platform's own operational facts are recorded, not inferred.** Every supervised
  part records its state and its last beat; a clean stop and a disappearance are different
  recorded facts; a runtime's absence is readable with a duration attached rather than
  reconstructed from a workflow UI after the fact. *Reversal cost:* low — one table, one writer.

---

## Part 11 — Implementation packets this document cuts into

Proposed, in merge order. **Sizing is the Manager's.**

| Packet | Content | Owner |
|---|---|---|
| P0-A | `jarvis/shell/service.py`: the single part table, `bootstrap()` with both postures, `serve_headless()` with signals and exit codes; `jarvis-run` console script; launcher re-pointed through it; `worker.py::main` deleted; layering exemption; `test_one_part_table`; root-path resolution (M10-F10) | platform-engineer |
| P0-B | `runtime_heartbeat` table + migration; `observability/heartbeat.py` store and pure assessment; Supervisor writes beats; the poller probe; `/api/ready`; `runtime` + `workers` health components; api-only self-declaration (M10-F2) | platform-engineer |
| P0-C | `jarvis/executive/liveness.py` — the `runtime.liveness_verdict` L1 rule, its Action Registry row, the parameter-register rows, transition-deduped notifications; the `failing` part state (5.4) | platform-engineer; §12.5 copy gated by operator-surface-engineer |
| P0-D | Wall-clock cron: the pure parser + validation refusal, `next_fire_at` on the context activity, `PATCH_WALL_CLOCK_SCHEDULE`, `schedule_timezone`, `record_late_wake` + its registry row, `wake_lateness_seconds`, both fixtures replaying, the scripted version pair | platform-engineer |
| P0-E | Scheduler: `sweep_interval_seconds` to Settings (M10-F5), per-step containment (M10-F6 residual), transition-deduped unreachable logging with periodic heartbeat, `managers_started` in the log trigger (M10-F9) | platform-engineer |
| P0-F | Deployment: `scripts/install-service.ps1` (NSSM) and the Task Scheduler fallback; compose `restart: unless-stopped` on all four services plus a `jarvis` service with a `/api/ready` healthcheck (M10-F14); `docs/DEPLOYMENT.md`; README/SETUP/GETTING_STARTED re-pointed | platform-engineer |
| P0-G | **Production runtime validation** — Part 8's V1…V7 executed on the real host under the owner's M10-F11 answer, reported with artifacts | platform-engineer |

**Sequencing.** A before everything: B's heartbeat writer needs the single supervisor, and every
later packet needs `jarvis-run` to exist. B before C: the verdict needs facts to read, and
computing staleness in two places is how two numbers that must agree stop agreeing. D and E are
independent of each other and of C, and can run in parallel once A has merged. F after B (its
healthcheck needs `/api/ready`). G last, and G is not a formality — it is the gate on Trading.

**Owner-gated.** P0-F's Mode 1 procedure and P0-G's V1/V3/V4 cannot complete until the M10-F11
escalation is answered. A and B do not wait on it.

**Cross-cutting risk.** P0-D is the only packet that touches a live workflow path. Three
executions are parked on the old path today (Part 0); it merges alone, and its verification
includes both committed fixtures replaying unedited.

---

## Part 12 — Findings

**M10-F10 — the headless entrypoint cannot inherit the launcher's relative paths.**
`launcher.py:74` tests `Path("docker-compose.yml")` and `launcher.py:96` builds
`Config("alembic.ini")`, both relative to the process working directory. A Windows service does
not start with a useful cwd, so migrations would silently target nothing and the compose probe
would always return False. NSSM's `AppDirectory` masks it; the code must not depend on that being
set. Category 1. Closed by P0-A's explicit root resolution.

**M10-F11 — Docker Desktop is per-user, so Mode 1 is not unattended without a decision.**
A LocalSystem service starting at boot finds Postgres, Redis and Temporal unreachable until a user
logs in and Docker Desktop starts. `bootstrap`'s `WAIT` posture makes this survivable but not
autonomous: a host that reboots with nobody to log in never starts serving. Three answers exist
(auto-login; native Postgres + NSSM-wrapped Temporal; a Linux/WSL2 host) and the choice is the
owner's, not engineering's. **Owner escalation. Gates V1, V3 and P0-F's Mode 1 procedure.**

**M10-F12 — LIVE: the platform is in the M9-F118 state right now.** Measured 2026-07-28 19:45
UTC: **zero** workflow pollers and **zero** activity pollers on `jarvis-platform`, against
infrastructure that has been up two days, with three ACTIVE companies whose Managers are parked
and whose last history event is `TIMER_STARTED` 13.5 hours ago. `/api/health` reports the workflow
runtime reachable, because it is. M9-F118 is not a past incident to design against; it is the
current state, and it is invisible. Category 1+4. The motivating exhibit for Part 3.

**M10-F13 — LIVE: the schedule has already drifted, and the drift is measurable.**
`bm-biz_0812…` (contract `schedule_cron = "0 9 * * *"`, read from the live database) started a
`1 day` timer at 22:40:31 on 07-26; it fired on time at 22:40:31 on 07-27 and was **not served
until 06:14:53 on 07-28 — 7h34m later**; the replacement timer anchored at 06:14:54. An outage
does not delay a cycle here, it *moves the schedule*, permanently and silently. This is M10-F4
with a measurement in place of an inference, and it is why 4.1 treats wall-clock computation and
anti-drift as one fix rather than two. Category 1. Blocking for market hours.

**M10-F14 — the compose stack's missing restart policy, confirmed against the running system.**
`docker-compose.yml` declares no `restart:` key, and `docker inspect` reports
`RestartPolicy.Name=no` on all four live containers. They have survived two days only because
nothing killed them. Confirms the ratification review's strengthening of M10-F7 against a running
system rather than a file. Category 1. Closed by P0-F.

**M10-F15 — the launcher's refuse-on-missing-database posture is wrong for a service.**
`launcher.py:206-211` exits when the database is unreachable. Correct for an interactive command
with a human present; for a service it converts a dependency-ordering problem into a restart loop
and reports it as one. The headless entrypoint needs a *waiting* posture the console must not
inherit, and the difference has to be a parameter of `bootstrap` rather than a fork of it.
Category 4. Closed by P0-A's `WAIT`/`REFUSE`.

**M10-F16 — there is no readiness endpoint, and `/api/health` cannot become one.** By D-016's
degradation ladder `/api/health` always answers 200 with a narrative body — correct for an
operator, useless for a container healthcheck or a service throttle, to which 200 means "send
traffic". Readiness and health are different questions and one endpoint cannot answer both without
lying to one caller. Category 1. Closed by P0-B's `/api/ready`.

**M10-F17 — the Executive cannot see the runtime, by D-038's own import rule.**
`jarvis/executive` may import only `registry`, `budget`, `kpi`, `observability` and
`notifications`, so the layer that raises every other platform alert cannot import
`jarvis.runtime` or `jarvis.kernel` to ask whether anything is polling. This is not a defect in
D-038 — it is the rule working — but it means the liveness fact must land in `observability` and
the Temporal probe must be injected by a composition root. Recorded so that a future packet
reaching for the direct import knows it is breaking a decision rather than fixing an oversight.
Category 3. Resolved by design in 3.3.

**M10-F18 — the platform records nothing about its own operation.** No table, row, or file states
that a runtime existed, which parts it ran, whether it stopped cleanly, or when it last spoke.
Every liveness question is therefore answered by after-the-fact inference from Temporal's UI —
the forensic reconstruction M9-F118's report had to perform, and the reason "the wakes had fired
7.5–20 hours earlier" was a discovery rather than a notification. Category 1+4. Closed by P0-B and
D-060.

**M10-F19 — the part table is implicit, and nothing enforces that there is only one.**
`Supervisor.add` is called from exactly one module today (`launcher.py:218-221`), but that is a
convention, not a property: a fifth entrypoint could compose a fourth different runtime tomorrow
and no gate would notice — which is exactly how three composition roots came to disagree without a
single commit to blame. The same argument `tests/test_layering.py`'s own docstring makes about
forward imports applies verbatim here. Category 4. Closed by P0-A's `test_one_part_table`.

---

## Verification

Gates run on this lane: docs-only change, expected exit 0. No merge, no push, no `DECISIONS.md`
edit, no worker started, no port bound, no unowned process touched, no `.env` contents read or
printed, $0 spent. Live Temporal and Postgres reads were **read-only** (`DescribeTaskQueue`,
`ListWorkflowExecutions`, `GetWorkflowExecutionHistory`, `DescribeWorkflowExecution`, one `SELECT`
over `business_instances`) and are the source of Part 0, M10-F12, M10-F13 and M10-F14. Nothing was
written to either. The four running containers were inspected and left running. Nothing is
implemented; the Part 10 decisions and Part 11 packets are for the Manager.
