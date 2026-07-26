# Jarvis — rules that bind every agent in this repo

Jarvis is an AI Enterprise Operating System: a platform that runs autonomous businesses under
human approval. The Architecture Specification v1.4 (owner-held) is the constitution; nothing
below may contradict it, and conflicts are flagged, never silently resolved.

## If you are the Engineering Manager starting a session
Read `HANDOFF.md` first. It records what has and has not been executed, which matters more
here than usual: most of this suite was written without a working interpreter.

## Read before touching anything
- `docs/DECISIONS.md` — every implementation decision (D-001…D-017) and defect finding. If your
  task touches a numbered decision, read that entry first.
- `docs/DEPENDENCIES.md` — milestone layering. A package imports only its own milestone or
  earlier; the only exceptions are the composition roots listed there.
- `docs/ROADMAP.md` — current milestone and report format.
- `docs/PRODUCT.md` — the product objective and philosophy. Operator-facing work is measured
  against it, and the product-reviewer gates milestones that have a surface.

## Invariants enforced by tests (run them; do not argue with them)
- **Layering**: `tests/test_layering.py`. New package → assign it a milestone there AND in
  docs/DEPENDENCIES.md.
- **Operator language (§12.5)**: `tests/test_operator_language.py`. No workflow/agent/worker/
  retry/token/etc. vocabulary in anything an operator can read — UI, labels, notifications,
  health summaries.
- **Workflow determinism (D-004)**: `tests/test_manager_determinism.py`. Nothing nondeterministic
  in `jarvis/manager/workflow.py` — no clock, no id minting, no I/O imports, every activity
  timeout-bounded.
- **Business types are data (D-014)**: `tests/test_affiliate_type.py` asserts zero
  functions/classes in type modules. Finance and later types must pass the same shape of test.

## Security boundaries (never weaken, always full-review)
- Identity derives from the Temporal workflow id (D-002); never trust request-declared identity.
- Models propose intents; the platform attaches scopes and resolves `needs_approval` (D-013).
- Approval text renders from stored values, never model prose (D-011).
- Tools run only on the approved-action path; credentials materialise only inside the tool call
  (D-015). Capital actions never graduate (spec §8).

## How work is delegated
`docs/DELEGATION.md` is the operating manual: the subagent roster, how the Engineering
Manager routes tasks and chooses models, the work-packet and report formats, and the
escalation protocol. Read it if you are unsure what you are allowed to decide.

**You never make architectural decisions.** If a task requires changing a layer, a
responsibility, an invariant, or an unspecified mechanism, STOP and return an ESCALATION
block (format in DELEGATION.md). An escalation is a successful outcome, not a failure.

## Working rules
- `bash scripts/gates.sh` before reporting complete. Its exit codes are a contract:
  `0` passed · `2` a gate ran and FAILED — fix it · `3` a gate could not run (offline or
  missing toolchain) — structural gates passed but the full suite is UNEXECUTED and your
  report must say so. Never describe a `3` as verified.
- New unspecified mechanism → add a D-entry to docs/DECISIONS.md. New dormant component → add a
  deferred-completion ledger row in docs/DEPENDENCIES.md.
- Patch scripts must assert their target exists before replacing (see finding M5-F2).
- Distinguish clearly in reports: verified-by-execution vs written-but-unexecuted. This
  project has been burned by that exact gap (finding M5-F5); blurring it is a defect.
- Never edit the spec. Never add speculative features (§14): demonstrated need only.
