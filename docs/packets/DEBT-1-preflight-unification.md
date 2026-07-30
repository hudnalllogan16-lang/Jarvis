# Packet DEBT-1 — preflight / health check-logic unification (M8-F44, M9-F155)

Lane: `debt-1` · Branch: `lane/debt-1` · Owner: platform-engineer · Authority: the
M8-F44 and M9-F155 finding records in `docs/DECISIONS.md` (read them first — they
define the duplication precisely) and design D-016's degradation ladder.

## Mandate

The preflight checks (`jarvis/shell/service.py` bootstrap path) and the health
components (`jarvis/api/app.py`) grew parallel implementations of the same questions —
database reachable, migrations at head, model configured, Temporal reachable — twice
deferred (M8, M9). Unify to ONE implementation per question, consumed by both surfaces:

1. Each check becomes a single pure/async function with one home (likely
   `jarvis/observability/` or wherever the finding records point — follow the records
   and the D-038 layering rule, not convenience).
2. Preflight and the health endpoint call the same functions; their DIFFERENT
   presentations (exit codes 2/3 and WAIT posture vs component narratives) stay exactly
   as they are — this packet unifies the questions, never the answers' rendering.
3. Behavior must be provably unchanged: the existing preflight tests and health tests
   pass unmodified except where they asserted on internal duplication itself.
4. If unification would change ANY observable behavior (ordering, timing, a message),
   stop and report it instead of shipping it.

## Boundaries

No new checks, no removed checks, no Settings changes, no endpoint changes. The
running live service on this host must not be touched.

## Gates

`bash scripts/gates.sh` exit 0 (pytest via python -m — do not change; M10-F36). Commit
on `lane/debt-1` only; never merge/push. Report 120/200 words: the one-home location
chosen and why the records support it, proof of behavior preservation, gates + count.
