# M7 Execution Plan — Finance Tracking Business (pilot of the D-026 organization)

Status: awaiting owner approval. No packets dispatched. Concurrency deliberately capped at
**2 implementation lanes** — the milestone validates the workflow as much as the feature.

## 1. Objective and the question M7 exists to answer

Spec §13 Step 3: Finance Tracking Business — read-only, exercises the KPI/dashboard pattern,
**no execution capability**. The architectural question is D-014's claim, untested until now:
*a second business type is addable as pure data, with zero changes to generic machinery.*
A packet that gets blocked on that claim has succeeded — the blockage is M8's design input.

**Owner checkpoint required before the Finance company launches** (Defaults in Force):
sign-off on the type's `compliance_requirements`, and on the Manager's proposed data-source
scope: Finance Tracking reads *operator-configured metrics and public data via the Research
capability only* — it does not read other businesses' ledgers or memory (cross-business
visibility is Executive Layer territory, M9, and §10 isolation stands). If you want it to
track the portfolio's own companies instead, that is an M9 conversation, not an M7 packet.

## 2. Packet decomposition

| Packet | Lane | Agent (model) | Finding range | Summary |
|---|---|---|---|---|
| M7-1 Finance type definition | A | business-type-author (sonnet) | M7-F1–F9 | Pure-data type module: schedule-based wake, capability permissions (research, finance), KPI schema + targets, prompt/template config, draft compliance_requirements, **empty declared_action_types** (read-only = nothing approvable). D-014 gate must pass; generic machinery untouchable; being blocked = escalation = the milestone's answer. |
| M7-2 Carried surface follow-ups | B | operator-surface-engineer (sonnet) | M7-F10–F19 | M6 closure items scheduled "before the next surface milestone": F1 notifications reconcile against reality on read; F2 drop stripped-id parentheticals; F6 notification bodies through the render boundary; runtime-§12.5 term-list morphology ("woken", "business"). |
| M7-3 Provision + live run | A (after M7-1 merges) | workflow-engineer (opus) | M7-F20–F29 | Create the Finance company through the real API; Manager wakes on schedule; research/finance capabilities run; KPI series recorded; health computed; Decision Log narrates; dashboard shows both companies. Proves the no-approval cycle shape and D-014 live. Spend cap ~$5. Any generic-code need → escalate, do not code. |
| M7-R1 Reserve: cosmetic follow-ups | B (after M7-2 merges) | operator-surface-engineer (sonnet) | M7-F30–F39 | F3 ("Doing now" tense/label), F4 (create-dialog error style), F5 (sub-stall wording). Dispatched only if wave capacity allows (the 70% rule); otherwise carried. |
| M7-4 Architecture audit | — (read-only) | architecture-auditor (opus) | — | Headline question: did D-014 survive? Plus the standard invariant/verification sweep. |
| M7-5 Product review | — (read-only) | product-reviewer (opus) | — | Two-company dashboard, finance KPIs in operator language, follow-up verification. |
| Close-out | — | docs-writer (sonnet) + Manager | — | HANDOFF/ROADMAP/DEPENDENCIES updates; Manager writes docs/reports/M7.md. |

## 3. Dependency graph and waves

```
Wave 0 (parallel):   M7-1 (lane A)        M7-2 (lane B)
                          │                    │
Wave 1:              M7-3 (lane A)        M7-R1 (lane B, capacity-permitting)
                          │
Wave 2 (parallel,    M7-4 + M7-5  (read-only, run against main while any
 read-only):                       remaining lane work continues)
Wave 3:              REVISE round if verdicts demand → close-out docs → tag m7-baseline
```

M7-1 → M7-3 is the only hard edge (the type must exist to provision). M7-2 is fully disjoint
(surface files; M7-1 touches only `jarvis/businesses/` + its test). Reviews overlap whatever
is still running, per D-026 scheduling rules.

## 4. Lane and merge mechanics (exactly as DELEGATION now documents)

- Lanes: `git worktree add ../Jarvis-lanes/m7-1 -b lane/m7-1` (same for m7-2, m7-3, m7-r1),
  `.env` copied in; live-verification lanes get `scripts/lane_env.py create <id>` overrides —
  except M7-3, which deliberately runs against the default stack: its purpose is proving the
  real dev topology with a second real company beside Summit Trail Gear.
- Merge queue order: **M7-1 first** (data-only, lowest risk, unblocks A), then M7-2, then
  M7-3, then M7-R1. Main gates after every merge; a packet is done only when main is green.
- Serial resources: no migrations expected (any migration need in M7-1/M7-3 is an escalation —
  a data-only type requiring schema change is a D-014 finding). conftest untouched; finding
  ranges pre-allocated above; dependency changes batched by the Manager (none expected).

## 5. Verification plan

1. Lane gates (628 baseline) green in every worktree before merge; main gates after every merge.
2. M7-1 acceptance: the D-014 data-only AST test covers the Finance type exactly as it covers
   Affiliate; type installs via `ensure_builtin_types` version-gating (M6-F22 lesson).
3. M7-3 acceptance is the live slice: company visible via API and dashboard, ≥1 completed
   scheduled cycle with KPI rows + Decision Log entry, health banding live (D-020 amendment
   fires if targets are set and unmet), **zero approvals generated** (read-only proven), spend
   within cap, replay fixture captured if the no-approval cycle shape diverges from M6's.
4. M7-4 MERGE + M7-5 SHIP both required to close (same as M6).
5. Regression: the M6 evidence trail (Summit Trail Gear) remains intact and its history
   untouched — verified read-only in M7-3's report.
6. Workflow-pilot verification (the meta-goal): the milestone report must state what the
   2-lane workflow cost and saved — merge conflicts encountered (expected: 0), queue wait
   times, and whether wave-0 parallelism was real (timestamps from both lanes).

## 6. What is explicitly out of scope

M8 plugin framework work (even if D-014 friction tempts it — findings, not fixes). Executive
Layer / cross-business reads. Any new tool or execution capability for Finance. Resilience
ledger items (M6-F13/F17/F18/F33/F42) — they remain scheduled against production posture, not
M7. Speculative restructuring of any kind (§14).

## 7. Expected risks, named in advance

- **D-014 fails partially** (the type needs one generic accessor, one contract field, …):
  most likely single outcome; handled as escalation → Manager decision → possibly a small
  amendment packet with its own number. This is the milestone succeeding at its job.
- **The no-approval cycle shape surprises the Manager workflow** (M6 never ran a cycle that
  proposes nothing external): M7-3's opus routing and replay-capture requirement exist for
  exactly this.
- **Wave-0 lanes finish at very different times** (type definition is small; surface work is
  larger): acceptable — lane A rolls straight into M7-3 prep while B finishes; the queue
  absorbs the skew.

## 8. Dispatch readiness

On approval: packet files M7-1 and M7-2 are written first (with the owner's data-source and
compliance sign-off quoted inside M7-1), both lanes open, wave 0 dispatches in parallel.
Nothing dispatches before that approval.
