## Packet M6-0c: unresolved stuck work caps the health band (D-020)

**Agent:** platform-engineer   **Model:** sonnet — fully gate-covered (the failing test asserts
exactly the decided property), isolated module, trivially reversible.

**Objective**
Implement D-020: a company with one or more unresolved dead-lettered jobs never presents a
`healthy` band; `test_stuck_work_dominates_the_score` passes without being edited.

**Files in scope**
Read first:
- `jarvis/kpi/engine.py` — `HealthScore` (band property, ~line 55) and `KpiEngine.health()`
  (~line 161), which computes `stuck_count` already
- `tests/test_kpi_health.py` — the failing test (~line 102). Do not edit it.

Edit:
- `jarvis/kpi/engine.py` only.

**Context you need**
D-020 (quoted): "A company with one or more unresolved dead-lettered jobs MUST NOT present a
`healthy` band, regardless of its weighted score. The weighted formula (headroom 0.30 /
reliability 0.45 / attainment 0.25) remains the score; the band computation gains a hard
override: `stuck > 0` caps the band at `watch`." The weighted score itself is unchanged — do not
re-tune weights or thresholds. The mechanism is yours to choose (e.g. the dataclass carries
`stuck_count` and `band` consults it), but the numeric `score` reported to the operator must
remain the weighted value; §12.5 requires the components remain available as the "why".

**Acceptance criteria**
- [ ] `uv run pytest -q` — `test_stuck_work_dominates_the_score` passes; no regression
- [ ] A company with stuck work, full headroom, and full attainment reports its weighted score
      but a band of `watch` at worst
- [ ] `bash scripts/gates.sh` — report the exit code verbatim; if lint/format/pyright steps
      (never yet reached before M6-0) fail on files you did not touch, report, don't fix

**Out of scope**
Weight or threshold changes. Summary-copy changes beyond what the override needs (the existing
stuck-work summary line already leads). Anything outside `jarvis/kpi/engine.py`.

**Escalate instead of deciding if**
- Implementing the cap requires touching the API layer or dashboard
- You find another consumer that derives band independently from the raw score
