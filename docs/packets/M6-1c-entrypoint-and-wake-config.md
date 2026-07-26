## Packet M6-1c: API entrypoint loop fix (M6-F7) + Affiliate wake-condition correction (M6-F10)

**Agent:** platform-engineer   **Model:** sonnet — two small, decided, gate-covered fixes.
(Bundled deliberately despite one-packet-one-concern: each is a few lines, both are already
decided in DECISIONS.md, and neither needs judgement beyond faithful implementation.)

**Part 1 — M6-F7**
`python -m jarvis.api.server` returns 500 on every DB route: `asyncio.run(ensure_builtin_types())`
closes the event loop the asyncpg pool bound to, then `uvicorn.run()` opens a new one.
`jarvis/shell/launcher.py` already does this correctly — make the standalone entrypoint follow
the same shape (one loop owns both the setup call and the server lifetime). Add a regression
test if one can run without a live Postgres; if it cannot, say so explicitly rather than
writing a fake one.

**Part 2 — M6-F10 (decision quoted from DECISIONS.md)**
"remove `capability.result_returned` from the Affiliate wake conditions; schedule and
`approval.decided` remain." Rationale: under D-001 every capability result is awaited and
consumed inside the cycle that requested it, so the subscription only lets a cycle's own output
re-wake the business (observed live: 6 unclaimed events, sweep withheld to avoid the loop).
This is a data-only change to the Affiliate type module — `tests/test_affiliate_type.py`'s
D-014 data-only assertion must stay green. Update any test that pinned the old wake-condition
list; do not weaken what the tests assert about the remaining conditions.

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0; test count before → after
- [ ] `python -m jarvis.api.server` serves DB routes without 500 (verify against the running
      Postgres; services are up)
- [ ] Affiliate wake conditions: schedule + `approval.decided` only
- [ ] Report: live vs simulated, exactly

**Out of scope**
The Manager workflow, the ledger, approvals, the six stale `capability.result_returned` events
already in the store (harmless once unsubscribed — note them, don't purge).

**Escalate instead of deciding if**
- The entrypoint fix cannot reuse the launcher's shape without restructuring the launcher
- Any other business type or test depends on `capability.result_returned` waking something
