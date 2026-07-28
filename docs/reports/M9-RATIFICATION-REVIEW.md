# M9 Final Ratification & Operational Readiness Review

**Owner-commissioned independent validation.** Lane `lane/m9-validation`, cut from main
`2079746`. Design/review only — **nothing in this lane changes behaviour**, including the one
fix this review recommends (flagged for the Manager to dispatch; not implemented here).

**Method.** Nothing in `RUNTIME-AUDIT.md`, `M9.md`, or `DECISIONS.md` is taken as evidence for
itself. Every verdict below rests on source I read or a check I ran in this worktree after
`uv sync --all-extras`. Where I reproduced a claim independently the reproduction is shown.

**Live evidence caveat.** `docker compose ps` returned **no containers** — the stack is down,
exactly as at audit time. No live DB or Temporal read was performed, no worker was started, no
port was bound (the health-route reproduction constructs the ASGI app in-process and inspects
its router; it never serves). No port conflicts observed; no process touched. $0 spent. No
`.env` contents read or printed.

**Suite state, verified by me:** `uv run pytest -q` → **1239 passed in 22.02s**. This matches
`M9.md:3`'s "1239 tests" exactly.

---

## P1 — Audit Validation

Ten items: the central three-topology finding plus M10-F1…F9. **All ten Confirmed. None
Incorrect, none Superseded.** Two are Confirmed with the audit *understating* the problem;
those are marked `Confirmed+`.

| # | Finding | Verdict | Evidence I generated |
|---|---|---|---|
| — | **Central: three composition roots, not composing the same runtime** | **Confirmed** | `launcher.py:218-222` registers four supervised parts; `worker.py:202` runs three loops under a bare `asyncio.gather` (no API, no supervision); `api/server.py:26-33` builds kernel + types + uvicorn and **nothing else**. `pyproject.toml:19-20` declares exactly one console script (`jarvis = "jarvis.shell.launcher:main"`) — B and C are `python -m` only. |
| F1 | **Launcher's parts-aware `/api/health` is permanently shadowed** | **Confirmed (reproduced)** | Built the app and appended the second route exactly as `launcher.py:103-125` does. Result: **2 routes at `/api/health`, indices 22 and 27**; first FULL router match resolves to `create_app.<locals>.health` (module `jarvis.api.app`). The launcher's is unreachable dead code. Consumer confirmed dead-ended at `api/static/app/system.js:83`. Pinning test asserts `body["parts"] == []` (`tests/test_api_health_route.py:60`) and never asserts the launcher's route is served. |
| F2 | **api-only topology is silently non-autonomous** | **Confirmed** | `api/server.py:14-35` — no worker, no scheduler, no executive, and no log line or health component announcing the absence. `Supervisor` is unreachable from this path. |
| F3 | **Operator docs disagree; two are stale** | **Confirmed** | Read all seven cited lines verbatim. `README.md:8` "Current state: Milestone 5"; `:49` "Start it with `uv run python -m jarvis.api.server`" (the zero-autonomy topology); `:51-52` "The timers are correct but dormant"; `:135` "Nothing schedules work yet". `SETUP.md:230,249-250`; `:320-321` "There is no Business Manager and no scheduler"; `:338` labels the worker "prod topology". `GETTING_STARTED.md:39,51` are the only correct instructions. |
| F4 | **`schedule_cron` flattened to a drifting fixed interval** | **Confirmed+** | Executed `_interval_seconds` directly: `'0 9 * * *'`→**86400**, `'30 14 * * 1-5'`→**86400**, `'0 * * * *'`→3600, `'*/15 * * * *'`→3600, **`'0 9,16 * * *'`→3600**. The audit says "3600 or 86400"; it does not note that a legitimate twice-daily cron silently becomes **hourly — a 12× over-fire**, each wake billable and bounded only by `max_cycles_per_day=48`. Both shipped types use `"0 9 * * *"` (`affiliate.py:116`, `finance.py:190`; default `definition.py:78`). |
| F5 | **Sweep interval hardcoded / un-configurable** | **Confirmed** | `worker.py:104` default `interval_seconds: int = 300`; both callers (`launcher.py:148`, `worker.py:202`) pass only the kernel. `config.py:134` names the asymmetry against `ExecutiveSettings.tick_interval_seconds` in prose. |
| F6 | **Manager auto-start coupled to scheduler liveness** | **Confirmed** | Repo-wide search for `ManagerLifecycle` / `.reconcile()`: exactly one production call site, `scheduler/service.py:109`, plus the import at `:34`, the class at `lifecycle.py:33`, and two test files. Nothing else. |
| F7 | **No persistent autonomous posture anywhere** | **Confirmed+** | No `.service`/`.unit` file exists. `launcher.py:311-327` binds process lifetime to the window (`stop.set()`, `services.join(timeout=15)`). **Additional evidence the audit missed: `docker-compose.yml` contains no `restart:` policy at all** — so even the container path has no restart guarantee, strengthening F7 beyond what was reported. |
| F8 | **Types auto-installed; companies never auto-created** | **Confirmed** | `container.py:423+` iterates `_builtin_types` and calls `provisioning.install(definition)` — a **type**. `create_company`'s only production caller is `POST /api/companies` (`app.py:575`, invoking `provisioning.create_company` at `:593`). Correct, intended empty-state. |
| F9 | **Temporal outage makes the sweep a silent no-op** | **Confirmed** | `lifecycle.py:54-56` `if client is None: return 0` — no log. `service.py:316-318` identical in `dispatch_events`. `worker.py:119`'s log trigger is `renotified or expired or woken or reservations_released` — **`managers_started` is absent**, so a sweep whose only work was starting Managers is also silent. |

**Precision note (immaterial):** the audit cites `provisioning.py:290-330` for `create_company`,
which begins at `:260`; the cited range falls inside the function body. No substantive error.

**Assessment of the audit itself:** accurate, conservative, and honestly caveated. It
understates F4's severity and under-evidences F7. It claims F1 was "verified in-process, not
inferred" — I re-ran that verification independently and it holds.

---

## P2 — Milestone Boundary

The discriminator the owner named is decisive, and git settles it.

**When did the code ship, and what did its milestone promise?**

- `git log -S"_interval_seconds" -- jarvis/manager/activities.py` → **`1fd1e37` "Import Jarvis
  platform (M6 baseline)"**. The cron flattening **predates M9 by three milestones**. No M9
  artifact promised wall-clock scheduling; `activities.py:1921-1925` documents the v1 subset as
  a deliberate §14 scope choice.
- Both `/api/health` routes and the pinning test also trace to **`1fd1e37`** — the *shadowing*
  is likewise pre-M9.
- **But** `git log -S"Company runner" -- jarvis/runtime/worker.py` → **`6edb34f` "M9-7: the
  FAILED cycle becomes loud"**. M9-7's packet acceptance (`docs/packets/M9-7-failed-cycle-visibility.md`)
  requires the model check fail **"LOUD (supervisor-visible, operator-sentence per §12.5)"**,
  and `worker.py:47-53` states the operator "shows … 'Company runner — restarting' with a crash
  count in the **health banner**". **M9-7 published that claim on top of a route that was
  already dead.** The banner half is false as shipped.

| Finding | Category | Justification |
|---|---|---|
| **F1** | **A** | The *regression* predates M9, but **M9-7's accepted packet and shipped docstring promise operator-visible supervisor loudness that does not exist**. This is a failure against **published M9 behavior** — the only one in the set. Narrow: the *log* half works (`supervisor.py:122-131` warns with part name and crash count); only the operator-visible half is false. Fix is small and local. |
| F2 | **B** | Deployment/topology capability. No M9 packet promised api-only autonomy; the topology predates M9. Intentionally deferrable to M10's operational-readiness scope. |
| F3 | **C** | Planning oversight, documentation only. README/SETUP went stale at M4/M5 and no milestone owned refreshing them. Zero code. |
| **F4** | **B** (with a **C** sliver) | Ships at M6 baseline, documented as a deliberate v1 subset, never contradicted by an M9 promise → **not** a regression and **not** an M9 contract failure. It is deferrable operational capability that **blocks M10 market hours**. The **C** sliver: `domain/contract.py:181` calls the field a "Cron expression", overstating what runs — a documentation defect fixable independently. |
| F5 | **C** | Known and recorded as M9-F92; `config.py:134` already documents the gap in prose. Planning oversight; a ~5-line change, but nothing in M9 promised it. |
| F6 | **B** | Supervision/restart-policy concern. Self-heals under the intended topology (A); the exposure is Topology B's bare `gather`, which is an operational-posture question. |
| F7 | **B** | The definition of Category B — deployment, supervision, OS integration, restart policy. Already recorded as deferred at `INCIDENT-M9-F118:31-33`. |
| F8 | **C** | Informational; behaviour is correct. A doc note is owed so "no company running" is not misread as failure. |
| F9 | **B** | Operational observability of the supervision path. Missing code, but it is *operational* capability, not a broken M9 promise. |
| Central | **B** + **C** | The topology gap itself is B (deployment posture); its documentation half is F3's C. |

**Summary: A = {F1}. B = {F2, F4, F6, F7, F9, central}. C = {F3, F5, F8, F4-prose}.**

Exactly one finding must be fixed before `m9-baseline`.

---

## P3 — M9 Contract

Graded strictly against the three binding sources. **Aspirations are not graded.**

### (a) Owner's close-out directive objectives — DECISIONS.md:2064-2092

M9.md:46's "all ten close-out objectives met" refers to the owner's **four conditions + six
refinements** on the Governance specification. These were directions **on the specification,
before ratification** — that is the correct scope to grade them at.

| # | Objective | Verdict | Evidence |
|---|---|---|---|
| C1 | Authority platform-wide on every executable action | **Completed** | Imported the registry: **24 actions**; L1=13, L3=6, L0=4, L2-tactical=1; cross-constraints validated **at import** (`_validate`, `authority.py:282`); 25+ tests in `tests/test_action_registry.py`. |
| C2 | POLICY formally defined, verbatim | **Completed** | Verbatim at `EXECUTIVE-GOVERNANCE.md:572` and `:1707`; four policy tests in `tests/test_parameter_register.py`. |
| C3 | Decision Lineage as first-class proof tree | **Partial — deferral RECORDED, correctly** | Concept complete in doc (Part 12.2 wave G3a). Not implemented. Recorded at `M9.md:55-56` ("ships with its first producer — no dormant tables") and in `authority.py:40-49`, which names the deferred actions and cites §14 against registering an action whose code does not exist. **Per the review's terms: recorded, therefore not marked missing.** |
| C4 | Authority inherited downward, never upward | **Completed, with a recorded honest limit** | Layers 1–2 built with **negative controls** (`test_the_inheritance_detectors_detect`, `test_the_inheritance_detector_is_not_trigger_happy`, `test_no_module_emits_an_action_above_its_declared_level`). Layer 3 (runtime `context_level >= action_level`) **cannot** be built — no execution-context authority level exists; recorded as M9-F134 in `authority.py:57-60`. |
| R1 | Two ladders (operational / financial) | **Deferred — RECORDED** | Wave G2b, doc 12.2. Not shipped. |
| R2 | Confidence gains a fourth state | **Deferred — RECORDED**, cheap partial shipped | Wave G2a. Verified partial: `app.py:383-393` suppresses "Running normally." when the last recorded round did not finish. |
| R3 | Explainability gains AUTHORITY — nine fields | **Deferred — RECORDED** | Wave G3b. |
| R4 | Plugin trichotomy | **Completed** | Doc 8.3; `authority.py:30-37` states it as the *reason* authority is not contract data. |
| R5 | Provenance extends to everything | **Completed** | `domain/provenance.py` `ProvenanceHead`; three dedicated tests incl. frozen-ness and honest-empty defaults. |
| R6 | L4/L5 reserved | **Completed** | Verified by import: `RESERVED_LEVELS = {L4, L5}`, both empty; `test_reserved_levels_are_empty`. |

**Verdict: M9.md:46's claim is accurate as scoped.** It would be misleading only if read as "all
ten mechanisms ship" — and M9.md does not claim that; it scopes enforcement to G1 explicitly
(`M9.md:17`) and lists the G2/G3 items among M10's preconditions.

### (b) M9 packet acceptance criteria

| Packet | Verdict | Evidence |
|---|---|---|
| M9-1/1a/1b/1c/1d Executive | **Completed** | `runner.py:134-140` runs rollup → census → both alert families → halt in design Part 7's order; wired at `worker.py:182-191`; 204 tests pass across the twelve executive/governance/dispatch suites. |
| M9-4 decline persistence | **Completed** | Migration 0007 + version-keyed suppression, recorded and tested. |
| M9-G1a/G1b governance | **Completed** | Registry, parameter register, provenance heads, namespace + ratchet + unregistered-action refusal — all test-backed with negative controls. |
| **M9-7 failed-cycle visibility** | **PARTIAL — the one unmet commitment** | (1) FAILED-cycle notification: shipped. (2) Startup model validation: shipped (`worker.py:68-79`) and it *does* fail loud **into the log**. **But the acceptance criterion "supervisor-visible" is not satisfied at the operator surface** — the parts list the banner would render is permanently empty (P1/F1). |
| M9-9 product REVISE | **Completed** | Both checkable fixes verified in code: normality suppression (`app.py:383-393`) and `never_measured` recounted on **recorded readings** (`executive/health.py:76-89`). |

### (c) M9.md's explicit claims

| Claim | Verdict |
|---|---|
| "1239 tests" | **Verified exactly** — my run: 1239 passed. |
| "24 actions, cross-constraints at import, L4/L5 reserved" | **Verified exactly** by direct import. |
| "The deterministic Executive … complete and live" | **Completed** — code trace + 204 tests. Note "live" is unverifiable today (stack down); it is true as *operates-as-designed*. |
| "All ten close-out objectives met" | **Accurate as scoped** (see (a)). |
| Readiness: "YES — recommend m9-baseline" | **Qualified** — sound but for M9-7's unmet operator-visible half. |

**P3 bottom line: one unmet M9 commitment — M9-7's supervisor-visible loudness (F1).**
Everything else is Completed, or Partial-and-properly-Recorded.

---

## P4 — Executive Validation

Stack down → **tests + code trace only**, no live checks. All twelve relevant suites pass (204
tests).

| Component | Operates as designed? | Basis |
|---|---|---|
| Runner | **Yes** | `runner.py:134-140`, exact Part 7 sequence; idempotent-on-repeat via each step's own dedup. |
| Timer | **Yes** | `worker.py:175-194`; 60s from `Settings.executive.tick_interval_seconds` (`config.py:130`), configurable; **no tick overlap** — each tick awaited to completion before sleeping. |
| Census | **Yes** | `executive/health.py`; D-039; `never_measured` gated on recorded readings, not cycles. |
| Rollups | **Yes** | `executive/rollup.py`; D-040 window-naming; `platform_ceiling_usd` injected once per tick from one Settings value (M9-F78 resolved by construction). |
| **Confidence** | **Not implemented — deferral RECORDED** | Designed Part 6 / D-047. `authority.py:40-49` explicitly lists `portfolio.compute_confidence` and `confidence.state_transition` among actions deliberately **not registered** because their code does not exist (§14). **Verified as recorded; not marked missing.** |
| Governance mechanisms | **Yes** | Import-rule detector (D-038) proven both directions; ratchet, namespace, unregistered-action refusal all present with negative controls. |
| Action Registry | **Yes** | 24 actions; cross-constraints at import; L4/L5 empty; digest and autonomy-inventory pinned by test. |
| **Explainability standard** | **G3-gated — RECORDED** | Nine-field renderer is wave G3b; lineage ships with its first producer (`M9.md:55-56`, "no dormant tables"). **Verified as recorded.** |
| Capability dispatch | **Yes, and enabled** | `grep enabled jarvis/capabilities/*.py` → **zero matches**; no pool-level kill switch. Built per unit of work at `runtime/activities.py:70` via `build_pool` — request-scoped, not a startup singleton. Gated per-business by contract permissions, the contention gate, and the budget hierarchy. |
| Manager orchestration | **Yes** | One-per-business by workflow-id collision (`lifecycle.py:88-109`); `continue_as_new` at threshold using `continued()` (M8-F87 fix intact); `_await_wake` races timer against signal. |
| Alerts + breaker | **Yes** | Both alert families plus `record_platform_halt`; the breaker is **asked**, never second-guessed by a recomputation. |

**Verdict:** the Executive operates as designed. The two unbuilt items (Confidence, lineage) are
**correctly recorded deferrals**, not silent gaps — the code itself refuses to register actions
whose mechanisms do not exist, which is the strongest form that recording can take.

---

## P5 — Runtime Trace

Traced end to end in source:

```
python -m jarvis  →  launcher.main  →  launch()
  Settings → PlatformKernel → run_preflight
  → [docker compose up -d + re-check, ≤2min]  → hard stop if DB unreachable
  → alembic upgrade head  → ensure_builtin_types()   [TYPES only, never companies]
  → Supervisor{ api, worker, scheduler, executive }   ← restart w/ doubling backoff, cap 60s
       ├ api        → create_app → uvicorn                    (health route: see F1)
       ├ worker     → retry until Temporal reachable → run_worker
       │                → verify_configured_model (M9-7) → Worker(BusinessManagerWorkflow, activities)
       ├ scheduler  → run_scheduler → sweep() BEFORE first sleep
       │                → renotify / expire / reconcile_reservations
       │                → ManagerLifecycle.reconcile() → start_workflow "bm-{id}" per ACTIVE
       │                → dispatch_events() → signal wake / approval_decided
       └ executive  → run_executive → run_executive_tick every 60s
  Manager workflow: run() → cycle → activities → kernel.build_pool(svc) → CapabilityPool dispatch
                    → _await_wake(timer vs signal) → continue_as_new at CYCLES_BEFORE_CONTINUATION
  Cron path: contract.schedule_cron → _interval_seconds (activities.py:357)
             → CycleContext.schedule_interval_seconds → workflow timer   [flattened — F4]
```

**Answer to the owner's core question: autonomous execution is PRESENT and
topology-dependent — it is not INCOMPLETE.**

Every link in the chain exists, is wired, and is test-covered. Under Topology A or B an ACTIVE
company's Manager starts **within seconds** of boot (the sweep runs before its first sleep —
verified at `worker.py:116-136`), then runs durably on its own Temporal timer. Nothing is
disabled; there is no kill switch; sequencing within each topology is correct.

Two qualifications, both real and neither an incompleteness:

1. **Topology-gated.** Under Topology C the chain never begins, and nothing says so (F2). The
   README leads operators to exactly that topology (F3).
2. **Fidelity-limited and lifetime-limited.** Autonomy runs on drifting fixed intervals rather
   than wall-clock (F4), and the only supervised topology cannot outlive a desktop window (F7).
   Autonomy is implemented; a *supported way to sustain it unattended* is not.

---

## P6 — Baselining Recommendation

### **Option 2 — fix the verified regression only, then baseline `m9-baseline`.**

**Exact fix list (Category A only — the complete list, nothing else gates the tag):**

1. **Restore the parts-aware `/api/health` (F1).** Either pass the `Supervisor` into
   `create_app` and delete the launcher's duplicate registration at `launcher.py:103-125`, or
   have the launcher mutate the existing route's dependency. This is the sole place where a
   **published M9 commitment** — M9-7's accepted "supervisor-visible" criterion and
   `worker.py:47-53`'s health-banner sentence — is false as shipped.
2. **Re-pin the test (`tests/test_api_health_route.py`).** Keep the existing `create_app`
   assertion, and **add** a launcher-topology test asserting the *served* route reports
   populated `parts`. Without this the fix is unpinned and the regression recurs — the current
   test asserting `parts == []` (line 60) is precisely why this survived to M9.

Both are small, local, and carry no workflow-versioning risk. **I implement neither; the
Manager dispatches.**

**Why not Option 1 (as-is).** Baselining now immortalizes a milestone whose own report promises
operator-visible loudness that the operator cannot see, *and* pins a test asserting the broken
shape. A baseline is the wrong artifact to freeze a false claim into, and the correction is two
edits.

**Why not Option 3 (complete unmet commitments first).** There are no other unmet M9
commitments. G2 (Confidence, the two ladders) and G3 (lineage, nine-field renderer) are
**recorded deferrals with sound §14 reasoning**, not gaps — and the code enforces the deferral
by refusing to register mechanism-less actions. Requiring them before baseline would import M10
scope into M9, which is the scope creep P7 exists to prevent.

**Why not Option 4 (do not baseline).** The architecture is sound and worth freezing: 1239 tests
pass; governance enforcement is real and negatively controlled; the Executive operates as
designed; the autonomy chain is complete under the intended topology. No architectural defect
would be locked in by the tag.

**Non-gating recommendation (Manager's call):** the README/SETUP corrections (F3, Category C)
cost $0, touch no code, and today actively route operators to the zero-autonomy topology while
asserting "there is no scheduler". Worth riding along with the baseline commit — but the tag
should **not** wait on them, and neither should it wait on the owner's ratification package,
which is an owner action rather than an engineering one.

---

## P7 — The M9 / M10 Boundary

**M9 baselines the architecture. M10 makes it operable.**

**M9 ends at:** a deterministic Executive that computes and reports; a governance constitution
whose G1 enforcement layer is live and mechanically tested, with G2/G3 recorded as gated; an
operator surface that tells the truth about failure; and an autonomy chain that is complete and
correct *within a running topology*.

**M10 (Operational Readiness + Trading) begins at** everything required to keep that chain
alive, and everything needing wall-clock time or judgment. M10 owns:

- Headless supervised entrypoint (`jarvis-run`) — a re-composition of existing parts, not new
  runtime logic; keeps `launcher.py`'s "no logic here" property intact **(F7)**
- OS-level restart policy — service / unit / container. **Note `docker-compose.yml` has no
  `restart:` policy today**, so this is a genuine greenfield item **(F7)**
- Worker-staleness surfaced as a health component — closing M9-F118's silence
- api-only self-declaration **(F2)**; sweep observability **(F9)**; sweep interval to Settings **(F5)**
- Wall-clock cron **(F4)** — under D-033 workflow versioning; a hard prerequisite for market hours
- Wave G2 (Confidence + the two ladders) and wave G3 (lineage + the nine-field renderer), each
  landing **with its first producer**
- Trading Analysis at L2-tactical, with the evaluation sub-ceiling shipping **before** the first
  judgment model call
- The seven named preconditions at `M9.md:51-60`, plus the recorded pay-later list

**The test that draws the line, and prevents creep:** a finding belongs to **M10** if fixing it
changes how Jarvis is *deployed, supervised, or scheduled in wall-clock time*, or adds a new
governed capability. It belongs to **M9** only if it makes an **already-published M9 claim**
true. **Exactly one finding passes that test: F1.**

Two guards follow. First, F7's posture design is the genuinely large item in this set and must
**not** be pulled backward into M9 to make the baseline feel more complete — it is M10's
headline deliverable. Second, the baseline must be tagged on the architecture **as verified**,
not on the ratification package's return; conflating an owner governance action with an
engineering checkpoint would leave the architectural checkpoint hostage to a decision that does
not change a line of code.

---

## Verification

Gates: docs-only change on this lane, expected exit 0. No merge, no push, no `DECISIONS.md`
edit, no live worker started, no live DB or Temporal read (stack verified down), no port bound,
no unowned process touched, no `.env` printed, $0 spent. Nothing implemented — the two P6 items
are flagged for Manager dispatch.
