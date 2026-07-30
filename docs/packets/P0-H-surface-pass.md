# Packet P0-H — the owed M10 surface pass: consent labels, copy minors, liveness voice

Lane: `p0-h` · Branch: `lane/p0-h` · Owner: operator-surface-engineer · Authority:
spec §12.5 (operator voice), the M9 closeout residual list, and the P0-C lane's flag.

## Mandate

Three debts, all recorded, all owed to M10:

1. **Consent-button labels** — the M9 product review's residual. Find the recorded
   specifics first: search `docs/DECISIONS.md` and `docs/reports/M9*.md` for the
   consent-button and copy-minor findings (the closeout names "consent-button labels +
   four copy minors"). Implement exactly what was recorded; if the record is ambiguous,
   report the ambiguity rather than inventing copy.
2. **The four copy minors** — same records, same rule.
3. **§12.5 voice pass on P0-C's provisional liveness copy** — the P0-C worker flagged
   its operator-facing strings (outage/recovery/failing-part notices, the `workers`
   component summaries in `jarvis/executive/liveness.py` and `jarvis/api/app.py`) as
   provisional. Bring them to the platform's one voice: plain words, states not alerts
   (D-046), says what happened and what to do, never says "error" where a sentence
   would do. Compare against the existing voice in D-035's dropped-wake copy and the
   census tile copy before writing.

## Boundaries

Operator-facing strings and their tests only. No behavior changes, no new
notifications, no schema/registry changes. If a string lives in a test assertion,
update the assertion with the string — never weaken the assertion.

## Gates

`bash scripts/gates.sh` exit 0 (pytest runs via python -m; do not change that — host
App Control, M10-F36). Commit on `lane/p0-h` only; never merge/push. Report 120/200
words: each recorded residual found + closed (cite where recorded), any ambiguity hit,
gates + count.
