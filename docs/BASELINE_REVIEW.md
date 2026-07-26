# Baseline Review — pre-Claude-Code transition

A comprehensive review of Jarvis before treating the current state as the baseline and executing
the roadmap. Commissioned with an explicit instruction not to assume prior decisions are correct.

I want to be honest about my own bias up front: a review whose implicit goal is to find things to
change will always find them, and that would be the factory-expansion this transition is meant to
stop. So my standard was the opposite — confirm the baseline is sound, and raise only what would
actually cost something if left. Most of what follows is confirmation. The genuine findings are
few, and I've marked severity plainly.

Scale reviewed: 75 Python files, ~8,900 lines, 230 tests, 5 migrations, 22 decisions/findings,
13 agents, 10 documentation files.

---

## Verdict

**The architecture is sound and the baseline is ready.** No architectural risk rises to the
level of "fix before proceeding." The single most important fact about this codebase — that the
platform is wired end to end in code but unproven in execution — is exactly what M6 addresses, so
the roadmap is already pointed at the right thing. Proceed to M6, starting with the bootstrap.

The findings below are real but none are blockers. Two are worth doing early *within* M6; the
rest are watch-items.

---

## What I verified as sound (the reassuring part)

**Layering holds.** 75 modules, zero forward imports outside the composition roots. Both
entrypoint roots hold no logic. Every package is assigned a milestone. The invariant that has
governed the build since M1 is still true, mechanically, today.

**The architecture is connected, not just co-located.** I checked whether the large dormant-
looking packages (`llm/` 8 files, `capabilities/` 8 files) are actually reachable or built in a
vacuum. They are wired: `manager/activities.py` calls both the LLM layer and the capability
request path; `kernel/container.py` builds them. The end-to-end path exists *in code*. What's
missing is execution proof, not integration.

**Determinism is intact.** No clock, id-mint, or randomness in the workflow source. The D-004
gate still passes on the current tree.

**The decision record is consistent.** Every `D-0NN` referenced in code exists in DECISIONS.md;
no orphans. D-001 through D-018 are contiguous. The migration chain is unbroken
(0001←0002←0003←0004←0005).

**Documentation is complete and non-contradictory.** All ten docs present. The roadmap table,
the priority order, and the packet set agree with each other. HANDOFF's verified-vs-written table
matches what the code actually supports.

**The governance system does what it claims.** Both reviewers are genuinely read-only (no Edit/
Write/Agent tools). The coordinator genuinely cannot implement. The gate script genuinely
distinguishes ran-and-failed from could-not-run. These aren't prompt promises; they're enforced
by tool grants and exit codes.

---

## Findings

### F-1 — The 230 tests have still never run. *(Severity: high, but already scheduled)*

This is the one that matters, and it's not new — it's the thing HANDOFF and every recent report
have flagged. Every "verified" claim in this project rests on stdlib-only checks; anything
touching SQLAlchemy, Temporal, pydantic, or FastAPI is written-but-unexecuted. The test *count*
is a count of written tests.

Not a blocker only because M6-0 is precisely this task and is first in the queue. But it should be
said plainly: **until M6-0 runs, the true health of ~200 of those tests is unknown**, and the
first real execution may surface a cluster of failures. That is paid-down debt, not new risk —
but budget for it, and do not let a green-looking test count create false confidence before M6-0.

### F-2 — `llm/` and `capabilities/` are the largest unproven surfaces. *(Severity: medium)*

Sixteen files across the two, all reachable, none executed against anything real. The LLM
provider integration in particular has never made a live call. M6-1 (Manager live-run) is the
first thing that will exercise the LLM path, and M6-3 the first to exercise tool execution. If
early-M6 breakage concentrates anywhere, it will be here. Recommendation: when M6-1 runs, treat
"did a real completion call succeed and parse" as an explicit checkpoint rather than assuming it,
and let the worker report it as verified-vs-simulated.

### F-3 — Two `alembic.ini`-relative assumptions in the launcher. *(Severity: low)*

Noted in HANDOFF already: `_apply_migrations` builds `Config("alembic.ini")` from a relative
path (fails if the working directory isn't the project root) and runs with no error handling (an
alembic failure crashes the launcher rather than degrading). Neither has bitten because the real
runs happened from the root. Worth a one-packet hardening pass at some point, but not urgent and
not M6.

### F-4 — Test-to-surface ratio is uneven, by design but worth watching. *(Severity: low)*

The structural invariants (layering, §12.5, determinism) are heavily gated; the *behavioural*
paths are heavily written but unexecuted. That's the correct order — structure first — but it
means the gate suite's current green is louder about *shape* than *behaviour*. As M6 proves
behaviour, the balance corrects itself. No action; just don't over-read the structural gates.

---

## Decisions I challenged and am NOT changing

Per the instruction to challenge rather than assume:

- **The one-process shell (D-016).** Challenged: does collapsing worker+API+scheduler into one
  dev process blur the architecture? Answer: no — it's a composition root, logic-free, and the
  layering test enforces that. The production topology is unchanged. Keep.
- **Business types as pure data (D-014).** Challenged: is zero-code really achievable for a
  second type, or is it aspirational? Answer: unknown until M7, and that is *exactly* why M6
  proves the platform on one type first. The reframing to a vertical slice already de-risks this.
  Keep, and let M7 be the real test.
- **Two separate reviewers.** Challenged: is the product-reviewer redundant with the auditor?
  Answer: no — correctness and experience are genuinely different questions and the GOOD/BAD
  examples in the charter show they'd produce different findings on the same screen. Keep.
- **The coordinator layer.** Challenged: is it worth the indirection for a solo-run project?
  Answer: its value is context preservation, which scales with project length, not team size.
  Keep, but it's fair to skip it for single-packet work (its own charter already says so).

None of these needed changing. I'm recording that I looked, so "we kept it" is a decision rather
than an omission.

---

## Opportunities to simplify (offered, not urgent)

- **`kpi/` and `notifications/` are 2 files each** — small enough that if either stays thin
  through M6, it's a candidate for folding into a neighbour rather than standing as its own
  package. Not now; flag for whenever their milestone next comes up.
- Nothing else. The package structure is proportionate to the domain; I looked for premature
  abstraction and didn't find a compelling case to consolidate anything else.

---

## Recommendation

Treat the current architecture as the baseline. Address nothing from this review *before* M6 —
F-1 and F-2 are handled *by* M6-0 and M6-1, and F-3/F-4 are low. Begin the roadmap.

The next objective is not to make Jarvis launch. It launches. The next objective is to make one
company travel the whole path — create, wake, act, ask, approve, execute, record — and in doing
so prove the platform is real. That is M6, and it is the right next thing.
