# M10 Organizational Review — independent, owner-commissioned

Evidence: `SUBAGENT-ORG.md`, `FABLE-RETRO.md`, `M9.md`, `M9-CLOSEOUT.md`, `RUNTIME-AUDIT.md`,
`DELEGATION.md`, D-019/D-026/D-037, git `m6-baseline..m9-baseline`, 59 packets.

## 1. Process verdict — D-037, measured

**Validated; it beat its forecast.** Lane-merge cadence, *active* windows: M7 16.6 min/merge
(2 lanes, 10/166 min) → M8 14.6 (3 lanes, 13/190) → M9 **9.7** (4 lanes, 17/165 in the
22:39–01:24 core). +50% on M8, above the predicted +25–35%; test delta agrees (+241, +264).
Rolling dispatch, prep pipelining and warm continuity are proven. Three defects:

- **The serial-resource list is stale.** Conflicts rose 1/13 (7.7%, 3 lanes) → 3/22 (13.6%, 4
  lanes); all lane-resolved, no post-merge failures. But all three hit files the list omits: `api/app.py` (1225 lines, 6 M9 touches), `static/app/*.js`, `registry/`.
  It still names `index.html`, which M8 split into 17 modules.
- **Rolling dispatch deleted its own safety net.** The m9-8 lane sat empty until the owner nudged:
  the wave barrier used to make a dropped dispatch visible. Verify-dispatch-after-commit is a
  habit, not a mechanism.
- **The 70% rule is dead** — M8 booked 100% of 3, M9 ran 4. Retire it.

**The bottleneck moved as the retro predicted.** M9 spanned 14h14m; ~3h were merge-productive —
the rest is review and owner-decision latency, now the constraint rather than lane count.

## 2. Architecture and governance fitness

Architecture needs no change — trading lands as an llm-fenced package with a registry entry
(audit-verified). Governance is the right shape: authority is enforced *mechanically*, so
judgment is a registry entry, not a code branch. Two process gaps:

- **Nothing asked "can this run unattended?" for nine milestones.** RUNTIME-AUDIT found three
  composition roots and no headless posture. Add a **deployability criterion** at milestone close.
- **M10 leaves gate coverage** — the routing rubric's main economic lever. Judgment quality is not
  mechanically checkable, so packets drift to Opus unless a harness exists first. **The evaluation
  sub-ceiling is the gate that keeps M10 affordable, not merely a budget control**; ship it with
  pass/fail criteria first. Related: the 17 JS surface modules have no test runner.

## 3. Roster

Dispatches across 59 packets: platform-engineer 19, workflow-engineer 10, security-engineer 10,
operator-surface-engineer 9, experience-engineer 3, test/data/business-type/refactorer 1–2 each.
**Never fired: delivery-coordinator, spec-archaeologist, docs-writer.**

- **Retire `delivery-coordinator`** — its unit of work was the prepared wave, which D-037
  abolished. With it, dead infrastructure: `docs/runs/` is **empty**; the manifest/runlog pipeline
  produced zero records in four milestones.
- **Retire `docs-writer`** — docs rode implementation packets.
- **Keep `spec-archaeologist`; make it mandatory** before decision-touching packets. It never
  fired from habit, not absence of need: DECISIONS.md grew 1211 → 2239 lines (+85%).
- **Add `judgment-engineer` (Opus).** No agent owns `jarvis/llm/`; SUBAGENT-ORG deferred it. M10
  warrants it: prompts, evaluation harness, the llm fence.
- **Phase 0 territory** (deployment, supervision, restart policy) → `platform-engineer`, not a new
  release agent — that is the speculation D-019 bars.
- **Fix the drift:** DELEGATION.md reads "Eleven agents" and omits `experience-engineer` (added
  M8 by D-028, dispatched 3×). Fourteen agent files exist; the manual has been wrong since M8.

## 4. Scheduling for M10

- **Phase 0 — 3 lanes.** Narrow, file-sharing work (`launcher.py`, `worker.py`, compose, docs);
  the lane-*n+1* evidence bar fails here.
- **Phase 1 (Trading) — 4; a 5th only for data-only type authoring.** M9 moved no ceiling.
- **Before 4 lanes run again:** rewrite the serial-resource list (add `api/app.py` region
  ownership, the JS modules, `registry/`) and keep a lane ledger reconciled at every merge.

## 5. Token efficiency

1. **Split the decision record** — the largest recoverable Manager-context spend. DECISIONS.md is
   M9's #1 write hotspot (19 touches), single-writer, 2,239 lines. Keep it as a decision index;
   move finding narratives to `docs/findings/M<n>.md`. D-037's recording cap slowed growth
   (+414 → +331) without solving it.
2. **Warm resumption as the recorded default** — measured 3–10× cheaper, yet only a preference.
3. **Mandatory `spec-archaeologist`** (§3); hold report caps at 300/500.

## 6. Recommended permanent organization

```
Owner — spec, amendments, approvals, capital · decision latency is now the top bottleneck
  │
  Fable — EM: decomposition · decisions · merge queue · lane ledger · memory
  │
  ├── Lanes (worktrees, rolling dispatch, cap 4; 5 for type work)
  │     platform-engineer (default; + deployment & supervision)
  │     workflow-engineer · security-engineer · data-engineer (serial migrations)
  │     experience-engineer · operator-surface-engineer · business-type-author
  │     judgment-engineer (new, M10) · test-engineer · refactorer
  │
  └── Read-only, Fable-direct, always parallel:
        architecture-auditor · product-reviewer · spec-archaeologist (now mandatory)
```

**Confidence:** high on process and roster (measured); medium on 4 lanes for Phase 1.

---

**Verification.** Docs-only lane; gates exit 0, 1240 passed. No merge, push, DECISIONS.md edit,
worker start, live DB/Temporal read, killed process, or `.env` print; $0 spent. **Port note:**
5432/7233/8233 LISTENING under PID 21632 while `docker compose ps` reports no containers; a
non-compose owner serves the stack. Reported, not touched.
