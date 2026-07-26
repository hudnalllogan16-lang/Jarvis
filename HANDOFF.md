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
Manager runtime + scheduler · M5 Affiliate Business · Developer Shell (roadmap revision 3).

**Current — M6, the Affiliate vertical slice:** M6-0 through M6-3 are complete and
live-proven: first-ever suite execution → gates exit 0 (M6-0); live Manager cycles on
Temporal with live model calls (M6-1); a live approval roundtrip (M6-2); live tool execution
through the approved-action path with §10 credential containment (M6-3). M6-4 (architecture
audit) returned MERGE WITH FOLLOW-UPS and M6-5 (product review) returned REVISE; the REVISE
round (packets M6-4b, M6-5a) is in flight now. Detail below.

**Scale:** ~120 files, ~19,600 lines, 554 tests as of packet M6-4a (the count moves —
`pytest --collect-only` for the live number), 24 implementation decisions (D-001…D-024),
6 migrations.

**Next:** M7 Finance Tracking, once M6 closes — the second business type, and per D-014
("a business type is data") the real test of whether it is pure configuration over the slice
M6 just proved. Work packets are written and waiting in `docs/packets/`.

---

## The most important thing on this page

**The full test suite has executed, more than once.** That was the single biggest unknown
this file used to carry, and M6-0 through M6-3 closed it: not just the suite as a suite, but
a live Manager wake cycle on a real Temporal worker, a live approval roundtrip, and live tool
execution through the approved-action path. `docs/DECISIONS.md`'s M6 sections (D-020…D-024,
M6-F1…M6-F34) are the record of what running it actually found — real breakage, exactly as
expected from milestones written without a working interpreter, all fixed or tracked as an
open finding rather than papered over.

That does not mean everything is proven. What's still open is tracked as findings in
`docs/DECISIONS.md`, not as a blanket "unexecuted" caveat — read the entries directly before
trusting a summary of them, including this one:

- **M6-F13 / M6-F16 / M6-F17 / M6-F18** — budget-ledger gaps: `load_cycle_context` unguarded
  before a cycle exists, no real per-token pricing, `cycle_id` re-minted on activity retry,
  reservations orphaned by a worker dying mid-transaction.
- **M6-F25 / M6-F26** — the per-company ceiling reader is forward-looking only (no backfill or
  edit path), and dependent-invocation settlement doesn't yet reflect real granted-context
  cost.
- **M6-F33 (escalated)** — no `workflow.patched()` convention yet; M6-3 shipped by
  terminating and restarting the Manager rather than versioning the workflow.
- **M6-F34** — an executed approval reaches the next planning prompt as raw `approval:<id>`
  text with no executed-signal.
- **§12.5-at-runtime** — the vocabulary gate is proven statically (markup, copy, labels); a
  live model's own output reaching the operator surface hasn't been swept the same way.
  Bundled with M6-F34 into the pending resilience/prompt packet.

### Verified vs written, precisely

| Verified by execution | Still open |
|---|---|
| The pytest suite as a suite, first run M6-0 (554 tests collected as of M6-4a) | Concurrent budget-debit enforcement across parallel dispatch waves (M6-F12, escalated) |
| A live Manager cycle on Temporal, live model calls (M6-1) | Budget-ledger gaps: M6-F13, M6-F16, M6-F17, M6-F18 |
| A live approval roundtrip, D-006's loop closed (M6-2) | Per-company ceiling backfill/edit path (M6-F25); dependent-settlement cost (M6-F26) |
| Live tool execution, §10 credential containment (M6-3) | Workflow-versioning convention (M6-F33, escalated) |
| Alembic migrations against real Postgres (run live under M6-0…M6-3) | Executed-approval signal into planning (M6-F34); §12.5 at runtime (bundled) |
| The dashboard, rendered in a browser and inspected (M6-5) | Dashboard blank-render + the rest of the M6-5 REVISE list (packet M6-5a, in flight) |
| Layering invariant, 75 modules, 0 violations | `python -m jarvis.api.server` standalone entrypoint (M6-F7 — the launcher path is fine) |
| §12.5 vocabulary gate (static), workflow determinism AST gate, supervisor restart/backoff, capability contention gate, preflight DB classification, `scripts/gates.sh` exit-code contract, syntax across the tree | Security denial-persistence + tool empty-payload refusal (packet M6-4b, in flight) |

---

## The current milestone: M6, the Affiliate vertical slice

Roadmap revision 4 reframed M6. It is no longer "add the Finance type" — it is **prove the
platform end to end with one company**, before widening to a second type. The full path:

```
create company → Manager wakes → executes a capability → proposes an action →
approval generated → operator approves → tool executes → audit + decision trail recorded
```

That path has now been travelled, live, at least once. Packets:

1. `M6-0-bootstrap.md` — **done.** Established the real test baseline; the suite's first-ever
   execution. What it found: D-020 and M6-F1…M6-F4.
2. `M6-1-manager-live-run.md` — **done.** The Manager wakes and completes a cycle against live
   Temporal with live model calls (follow-ups M6-1b/c/d covered cycle-id minting, entrypoint
   config, and the reservation ledger — D-021/D-022).
3. `M6-2-approval-roundtrip.md` — **done.** An action needed approval, the operator decided,
   the cycle resumed — first live exercise of D-006 (follow-up M6-2b added dependent
   dispatches, D-023).
4. `M6-3-execute-and-audit.md` — **done.** The approved action executed through the tool
   boundary, credentials contained (§10), trail recorded — D-024.
5. `M6-4-slice-audit.md` — **done.** Verdict: MERGE WITH FOLLOW-UPS. Two code findings
   packeted as M6-4a (approval-payload visibility; D-002 identity assertion in Manager
   activities) — done, and the source of the current 554-test count. The doc rot the same
   audit found is this file and `docs/DEPENDENCIES.md`.
6. `M6-5-product-review.md` — **done.** Verdict: REVISE. Blocking finding: the dashboard
   rendered blank (a listener bound to a nonexistent element id halted the initial paint).
   Packeted as M6-5a, in flight now alongside M6-4b (security denial-persistence and
   empty-payload refusal fixes).

M6 closes when M6-4b and M6-5a land and M6-5 re-reviews clean. Finance Tracking is M7 — short,
because it exercises a path M6 already proved.

The desktop application itself is verified on hardware (M5-F5/F6/F7 all confirmed). The
transaction is now proven live too (M6-0 through M6-3); what's left is closing the findings
the audit and product review surfaced.

---

## Open items you inherit

**Deferred-completion ledger** (`docs/DEPENDENCIES.md`): closed. All four rows are now
Retired — `CredentialManager` was the last one open, and M6-3 gave it a live caller
(`execute_approved_action`, through the publish tool — M6-F28). Watch for new rows as M7
starts building a second business type.

**What actually needs attention now:** the M6-4/M6-5 REVISE round in flight (M6-4b, M6-5a —
see above), and two findings marked "escalated" in `docs/DECISIONS.md` that need a Manager
decision rather than a packet: M6-F12 (every D-003 budget ceiling is under-enforced across
concurrent debits — proven live, not fixed) and M6-F33 (no workflow-versioning convention;
M6-3 shipped by restarting the Manager instead of using one). Read both before scheduling M7.

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

> Read HANDOFF.md, then check the status of packets M6-4b and M6-5a — the REVISE round is
> what stands between M6 and M7.

Delegate it. Don't implement it yourself — that's the whole point of the arrangement, and a
security or product-surface packet in particular will generate a large volume of detail that
belongs in a worker's context rather than yours.
