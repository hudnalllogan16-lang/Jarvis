# Engineering Process Review — M10 (2026-07-28)

Owner-directed first-principles review under expanded execution capabilities (direct host
access, scheduled session wakeups, background process supervision, browser/web research
stack). Mandate: "Do not optimize around our current workflow simply because it exists."

**Verdict: the core process survives on evidence; the session-boundary layer around it does
not.** The packet/lane/gates organization was measured into existence and its numbers hold.
What the new capabilities actually change is everything *between* sessions — continuity,
monitoring, and away-time coverage — which was the genuine weakest layer.

## 1. Engineering Process Review

Current process: design docs cut into packets; packets dispatched to lane agents in git
worktrees; lane gates before merge; Manager merges one at a time; main gates after every
merge; conflicts bounced to the owning lane; decisions recorded in DECISIONS.md; owner gates
at constitutional boundaries. Every element traces to a recorded failure it prevents.

## 2. Bottleneck Analysis (ranked by measured impact)

1. **Session mortality.** M9 lost two agents to usage limits, one to a stall, one to a
   user-stop; this session crossed a usage boundary mid-flight with two lanes open. Each
   event costs hours of stall until the owner returns. *The* dominant bottleneck.
2. **Owner-decision latency.** §8 platform approvals stalled strategic L2 through M9;
   M10-F11 was open from design day until today. Not a process defect — these are real
   owner decisions — but latency is reducible by batching (see §7).
3. **Idle compute between sessions.** Nothing progressed while no session ran. Directly
   addressed by scheduled wakeups (new capability).
4. **Cold-context dispatch cost.** A single conflict-resolution round: ~400k subagent
   tokens, 202 tool calls. Warm continuity (3–10× cheaper, FABLE-RETRO) already mitigates;
   remains the right default.
5. **Sequential merge queue — measured NON-bottleneck.** 19 merges, 3 conflicts, 0
   post-merge gate failures in M9; the queue has never been the constraint. Retained.

## 3. Throughput Analysis

Throughput has never been limited by lane count (the 4-lane cap has bound only by design)
or merge serialization. M9: +264 tests in one milestone. M10 Phase 0: +201 tests (1240 →
1441) across five packets in roughly one working day of session time. The constraint is
wall-clock coverage — how many hours per day a competent orchestrator is alive — which is
exactly what scheduled continuity attacks.

## 4. Token Efficiency Analysis

Largest sinks, in order: cold founding mandates (mitigated: packet docs are single-source
mandates, agents read the repo rather than receiving prose); conflict-resolution round
trips (mitigated: lane-resolves protocol keeps context where it already is); design-doc
re-reads (accepted cost: the doc is the authority, that is the point). Structural
protections retained: the repo is the context store — compaction has hit this session
twice and work resumed from committed state + memory files both times. Rejected on token
grounds alone: any relay/orchestrator layer above this session (see Cowork review) — it
re-derives context the executing session already holds, from the same shared usage budget.

## 5. Autonomous Work Strategy

Runs unattended: packet implementation in lanes; gates; merges of clean lanes; docs; debt
reduction; soak execution and checkpoint monitoring; validation tests that do not reboot
the host. Owner-gated (unchanged, constitutional): product vision, architecture, security
model, external integrations, user-facing behavior beyond the roadmap — plus pushes to
origin, credentials, spend, and anything irreversible on host state outside the roadmap.

## 6. Personal Computer Utilization Plan

While the owner is away: P0-F lane work → merge; P0-G validation campaign (V2, V4-as-
measured, V5, V6, V7); the ~24h soak with scheduled checkpoint wakeups sampling scheduler
accuracy, heartbeat continuity, memory, queue health, and the audit/notification cross-
check; documentation; debt register items. After M10 closes: the Phase 2 competitive-
intelligence research runs on the browser/web stack. Out of M10 entirely (owner ruling
2026-07-28): the boot-path tests V1/V3 — cold-boot recovery is an infrastructure decision
for the next-phase deployment evaluation, not an engineering deficiency. Not while away:
GitHub pushes, Phase 2 before closeout.

## 7. Approval Boundary Redesign

No change to the boundaries themselves — they are constitutional (§15) and the review
found no evidence against them. Two operational mechanisms added: **decision batching**
(owner gates presented as option-sets when the owner is at the keyboard — M10-F11 was
cleared in one exchange today this way) and the **deferred-decision protocol** (work
proceeds around an open gate; the closeout states it; nothing silently assumes an answer).

## 8. Organizational Redesign

Retained intact: D-054 (4-lane cap, rolling dispatch, ledger, lane-resolves-conflicts,
Manager-merges-one-at-a-time, warm continuity). Changes adopted:
- **Continuity upgrade:** scheduled session wakeups become the standing recovery mechanism
  — a dead session is now a delay, not a stall-until-owner-returns.
- **P0-G executes as a Manager campaign, not a lane** — it needs the real host, elevation,
  and produces artifacts rather than code. Fixes it discovers go to lanes as usual.
- **Rejected again with new evidence:** orchestrator hierarchies (Cowork-above-Code) —
  same budget, less context, second summarization layer (M5-F5).

## 9. Long-Term Roadmap (10× codebase, multiple contributors, continuous development)

What scales as-is: worktree lanes (git-native), packet mandates, repo-as-memory, persona
reviewers. What must change with size: gates need sharding once the suite passes ~5
minutes; CI on origin becomes the second gate wall when pushes become routine; DECISIONS.md
gains an index before D-150; the Action Registry pattern (one emit site, refuse
unregistered) is already the multi-agent coordination answer — Jarvis's own governance is
the model for its development. What never changes: review-before-merge, evidence-before-
closure, one Manager authority per repo.

## 10. Implementation Plan

Now: P0-F cut + dispatched; P0-G campaign doc cut; M10-F11 deferral recorded. At P0-G:
scheduled checkpoints stood up for the soak. At closeout: nine deliverables + closeout
report + readiness assessment vs the owner's six criteria. After ratification: Phase 2
research stack. Prior-recommendation corrections: "away-time work cannot reach the local
stack" is **obsolete** (local scheduled wakeups exist); "peer console, not command chain"
and "the repo is the coordination bus" **stand**.
