# HANDOFF — read this first

You are picking up Jarvis as Engineering Manager. This document exists because the project
was designed and built across chat sessions that you cannot see; everything durable was
written into this repository, and this file tells you where things actually stand.

**Read in this order:** this file → `docs/BASELINE_REVIEW.md` (the pre-transition health check) → `CLAUDE.md` (loads automatically, but read it
deliberately) → `docs/DELEGATION.md` (how you delegate) → `docs/ROADMAP.md` (what's next) →
`docs/DECISIONS.md` (why everything is the way it is). `docs/DEPENDENCIES.md` when you need
the layering rules.

---

## What Jarvis is

An AI Enterprise Operating System: a platform that runs autonomous businesses under human
approval. The owner holds the Architecture Specification v1.4, which is binding — it wins
over any instruction, and conflicts get flagged rather than silently resolved. The platform
is generic; individual businesses (Affiliate, Finance Tracking, Trading) are configuration.

Your role: own the roadmap, architectural integrity, implementation decisions, and project
memory. Delegate implementation to the subagents in `.claude/agents/`. You are not the
primary implementer.

---

## Where the project stands

**Merged:** M1 Platform Kernel · M2 execution spine · M3 operator surface · M4 Business
Manager runtime + scheduler · M5 Affiliate Business · Developer Shell (roadmap revision 3) ·
M6 Affiliate vertical slice · M7 Finance Tracking (the pilot of the D-026 lane organization).

**M7 closed with both gates cleared:** architecture **MERGE with follow-ups**, product
**SHIP** after two narrow REVISE rounds (M7-5a, M7-5b). Verdicts and the open ledger are
recorded in `docs/DECISIONS.md` ("M7 closure") and `docs/reports/M7.md`. Detail below.

**Scale:** ~133 files, ~25,000 lines, 734 tests as of M7 closure (the count moves —
`pytest --collect-only` for the live number), 27 implementation decisions (D-001…D-027),
6 migrations.

**Next:** M8 Plugin framework (§13 Step 4, §4) — the general business-type installer and
packaging mechanism, generalizing from two real instances (Affiliate, Finance) instead of
one. It carries an unusually well-stocked design inbox out of M7 closure: the general builtin
installer (M7-F1); pre-wake context-snapshot staleness including day-ordinal/ceiling
consumers (M7-F45/F-B); contract-refresh-on-upgrade (F-A/M7-F62/M7-F24); a D-027 amendment
pass on metric semantics (M7-F33/F49), idle-cycle measurement (M7-F32), and
result-usefulness vs. invocation-success (M7-F60); a D-011 extension for operator-feed prose
(M7-F50/F-C); and the trivial M7-F48 (`installed_at` not refreshed on upgrade). No M8 packets
are written yet.

---

## The most important thing on this page

**The full test suite has executed repeatedly, most recently at M7 closure (734 tests, gates
exit 0).** M6-0 through M6-3 closed the biggest unknown this file used to carry: not just the
suite as a suite, but a live Manager wake cycle on a real Temporal worker, a live approval
roundtrip, and live tool execution through the approved-action path. M7 added the second live
proof, for a second business type: two COMPLETED cycles on a real Finance company (Portfolio
Watch), the platform's first-ever `kpi_values` rows (D-027), the owner's compliance rules
asserted verbatim at the outbound prompt boundary, and zero approvals across every live
cycle — "read-only" proven the strong way (both D-013 layers refusing probe proposals), not
by omission. `docs/DECISIONS.md`'s M6 and M7 sections are the record of what running it
actually found — real breakage, exactly as expected from milestones written without a working
interpreter, all fixed or tracked as an open finding rather than papered over.

That does not mean everything is proven. What's still open is tracked as findings in
`docs/DECISIONS.md`, not as a blanket "unexecuted" caveat — read the entries directly before
trusting a summary of them, including this one. Carried forward from M6 closure unchanged (M7
did not touch these):

- **M6-F13 / M6-F16 / M6-F17 / M6-F18** — budget-ledger gaps: `load_cycle_context` unguarded
  before a cycle exists, no real per-token pricing, `cycle_id` re-minted on activity retry
  (corroborated live again in M7 — M7-F25), reservations orphaned by a worker dying
  mid-transaction.
- **M6-F25 / M6-F26** — the per-company ceiling reader is forward-looking only (no backfill or
  edit path), and dependent-invocation settlement doesn't yet reflect real granted-context
  cost.
- **M6-F33 (escalated) — still required before any production posture.** No
  `workflow.patched()` convention yet; M6-3 shipped by terminating and restarting the Manager
  rather than versioning the workflow.
- **M6-F34 / M6-F42 / M6-F44** — an executed approval reaches the next planning prompt as raw
  `approval:<id>` text with no executed-signal; `CredentialManager` refusals carry no audit
  record; `/api/health` duplicates its checks across the shell/api boundary rather than
  sharing them (flagged duplication, not yet unified).
- **D-025.2 implementation** — the Postgres-only test lane the M6-4b decision requires.

New from M7, all recorded under "M7 closure" in `docs/DECISIONS.md` and folded into the M8
design inbox above: the pre-wake context snapshot is stale for the first cycle after any type
upgrade (M7-F45/F-B); contract-refresh-on-upgrade doesn't exist, so the attainment-direction
fix (M7-F30) only reaches companies created after type 1.0.2 — Portfolio Watch's live 45%
attainment is the unfixed arithmetic, 78% with direction (audit correction F-A); KPI metric
semantics need a follow-up pass (M7-F33/F49/F32/F60); operator-feed prose can still surface
milestone-labelled owner text by construction, since D-027.5 injects the compliance rules
verbatim (M7-F50/F-C, a D-011 extension question for M8).

### Verified vs written, precisely

| Verified by execution | Still open |
|---|---|
| The pytest suite as a suite, 734 tests as of M7 closure | Concurrent budget-debit enforcement across parallel dispatch waves (M6-F12, escalated) |
| A live Manager cycle on Temporal, live model calls, for two business types (M6-1, M7-3c) | Budget-ledger gaps: M6-F13, M6-F16, M6-F17, M6-F18; `cycle_id` re-mint corroborated live again (M7-F25) |
| A live approval roundtrip, D-006's loop closed (M6-2) | Per-company ceiling backfill/edit path (M6-F25); dependent-settlement cost (M6-F26) |
| Live tool execution, §10 credential containment (M6-3) | Workflow-versioning convention (M6-F33, escalated — required before any production posture) |
| The first live KPI measurement (D-027): `kpi_values` rows written, attainment on the dashboard, for a second business type (M7-3c) | Contract-refresh-on-upgrade (M7-F24/F-A/M7-F62); attainment direction reaches only post-1.0.2 companies |
| Read-only proven live: zero approvals, both D-013 layers refusing probe proposals, across every Finance cycle | Executed-approval signal into planning (M6-F34); §12.5 at runtime (bundled) |
| The D-026 lane organization, piloted across OPS-1 + nine M7 lanes: ten worktree lanes, ten merges, zero merge conflicts, zero main-gate failures after merge | D-027 amendment pass: metric semantics (M7-F33/F49), idle-cycle measurement (M7-F32), result-usefulness vs. invocation-success (M7-F60) |
| Layering invariant, 0 violations across the tree | The general builtin installer (M7-F1); `python -m jarvis.api.server` standalone entrypoint (M6-F7 — the launcher path is fine) |
| §12.5 vocabulary gate (static), workflow determinism AST gate, supervisor restart/backoff, capability contention gate, preflight DB classification, `scripts/gates.sh` exit-code contract, syntax across the tree | D-011 extension for operator-feed prose surfacing owner-authored milestone text (M7-F50/F-C) |

---

## M7 closed: Finance Tracking, and the D-026 lane pilot

M7 answered D-014's question — "a business type is data" — with a second real instance: the
Finance Tracking type is pure data (same AST gate as Affiliate, `tests/test_affiliate_type.py`
shape), version-gated through three upgrades (1.0.0 → 1.0.1 → 1.0.2), and its live company —
**Portfolio Watch** — ran real cycles that wrote the platform's first-ever KPI values (D-027),
with attainment reaching the dashboard. Read-only was proven the strong way: an empty
declared-action set, both D-013 layers refusing probe proposals, zero approvals across every
live cycle. The owner's seven compliance rules live on the stored contract and were asserted
verbatim at the outbound prompt boundary. The honest cost: hosting a second type took three
generic, data-shaped platform changes (installer tuple, KPI-mapping field, KPI-target
direction field) — not zero, as the milestone's plan had hoped, but all demonstrated need, all
audit-endorsed.

Both gates cleared: M7-4 (architecture) **MERGE with follow-ups**; M7-5 (product), after two
narrow REVISE rounds (M7-5a: company identity and KPI visibility invisible after creation;
M7-5b: an honest stuck-work label, explicit scales, escaping), final verdict **SHIP**. Full
detail, verification performed, and the known-limitations list: `docs/reports/M7.md`. Verdicts
and every finding: `docs/DECISIONS.md`, "M7-F1…M7-F69" through "M7 closure".

M7 doubled as the deliberate pilot of the D-026 lane organization (worktree lanes + a merge
queue, adopted because M6 ran ~95% serialized). Measured result, `docs/reports/M7.md`: **ten
worktree lanes counting OPS-1, ten merges, zero merge conflicts, zero main-gate failures after
merge** (628 → 734 tests). True wave-0 parallelism (two lanes fully overlapped, 11 and 24
minutes); a live lane and a code lane ran concurrently without interference; three unplanned
lanes were born from escalations, each packeted before code. The audit's explicit finding: the
lane workflow strengthened discipline rather than diluting it. D-026 is now the operating
model for implementation work, not a trial.

Three companies are live on the platform today: Trailhead and Summit Trail Gear (Affiliate),
and Portfolio Watch (Finance, read-only) — the first company of a second business type, and
the first to carry measured (not just targeted) KPIs.

**Next is M8, the Plugin framework** (§13 Step 4, §4) — generalizing the business-type
mechanism now that two real instances exist to generalize from, per §13's own ordering
("once two business types exist for real comparison"). See the design inbox above. No M8
packets are written yet — the next session's first job is writing the first one against that
inbox.

---

## Open items you inherit

**Deferred-completion ledger** (`docs/DEPENDENCIES.md`): closed again. All five rows are now
Retired — `KpiEngine.record` was the ledger's own worked example of the failure it exists to
prevent: built in M3, no caller for four milestones, never listed here so the debt accrued
invisibly until a live run found it (M7-F21: `kpi_values` had never held a row). D-027 gave it
a caller (`record_cycle_kpis`) and the row was added and retired in the same milestone
(M7-F34). Watch for new rows as M8 starts generalizing the business-type mechanism.

**What actually needs attention now:** M7 closed clean — no REVISE round in flight — so the
next session's real work is writing the first M8 packet against the design inbox above. Two
findings marked "escalated" in `docs/DECISIONS.md` still need a Manager decision rather than a
packet, unresolved since M6 and untouched by M7: **M6-F12** (every D-003 budget ceiling is
under-enforced across concurrent debits — proven live, not fixed) and **M6-F33** (no
workflow-versioning convention; M6-3 shipped by restarting the Manager instead of using one —
explicitly required to close before any production posture). Read both before M8 touches
anything that runs a live cycle.

**A coordination question for the owner.** During M5, work appeared in the tree that the
prior session had not written — a parallel implementation of the business-type mechanism in
`jarvis/businesses/` alongside one being built in `jarvis/plugins/`. It was reconciled onto
`jarvis/businesses/` (the better design: definitions persist in the Registry rather than an
in-process dict) and `jarvis/plugins/` was deleted. Findings M5-F1 through M5-F4 record it.
If more than one agent or person will write to this repo concurrently, agree a convention
before it happens again — the failure mode was silent, and a patch that matched nothing was
reported as applied.

**Untested code paths worth suspicion** (noted, not defects): `_apply_migrations` builds
`Config("alembic.ini")` from a relative path, so it fails if the working directory is not
the project root; it also runs with no error handling, so an alembic failure crashes the
launcher instead of degrading it. Both are in `jarvis/shell/launcher.py`.

---

## Working agreements carried forward

These came from the owner and hold unless the owner changes them:

- **Never edit the Architecture Specification.** Flag conflicts; don't resolve them.
- **Milestone boundaries are implementation artifacts, not architecture.** Resequence when
  implementation reveals a cleaner dependency order — but explain what changed, why the old
  order was suboptimal, why the new one is better, and classify the change as structural,
  architectural, or operational. Roadmap revisions 1–3 are worked examples.
- **Implementation is the elimination of ambiguity, not the addition of code.** When you find
  an implicit assumption, route it: architectural rule → the spec (owner's call);
  unspecified mechanism → `DECISIONS.md`; dependency → `DEPENDENCIES.md`; mechanically
  checkable property → a test, in preference to prose; infrastructure ahead of its caller →
  the deferred-completion ledger; incidental detail → a code comment.
- **Prefer executable guarantees over conventions.** This is why the layering rule, §12.5,
  and workflow determinism are tests rather than documentation.
- **Every completed feature should be reachable in the running application** as soon as
  reasonably possible. Milestone reports carry a "Surfaced in the Shell" item.
- **Milestone report format:** roadmap delta · dependency-graph delta · objective ·
  architectural justification · implementation decisions · defects found and corrected ·
  verification performed · known limitations · merge recommendation · surfaced in the Shell.
- **Distinguish verified from written, always.** The project has been burned by that gap
  (M5-F5). Blurring it is treated as a defect, and the auditor is instructed to flag it.

---

## Starting work in Claude Code

```bash
cd /path/to/Jarvis
claude
```

The subagent roster loads from `.claude/agents/`. `CLAUDE.md` loads into every worker
automatically. `scripts/gates.sh` is wired as a `SubagentStop` hook in
`.claude/settings.json`, so no worker can report completion over failing gates.

One caveat from the Claude Code docs: the directory watcher only covers directories that
existed when the session started. Since `.claude/agents/` ships in this repo it will be
present, but if you ever add the first file to a *new* agent directory mid-session, restart.

A reasonable first message to yourself:

> Read HANDOFF.md, then write the first M8 packet against the design inbox recorded under
> "M7 closure" in DECISIONS.md — that's what stands between M7 and M8.

Delegate it. Don't implement it yourself — that's the whole point of the arrangement, and a
security or product-surface packet in particular will generate a large volume of detail that
belongs in a worker's context rather than yours.
