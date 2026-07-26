## Packet OPS-1: parameterized lane environments (D-026.2, implements D-025.2)

**Agent:** test-engineer   **Model:** sonnet — test infrastructure and one small script;
fully gate-covered; trivially reversible. Finding range allocated: **OPS-F1–OPS-F9**.

**Objective**
Two development lanes can run the full gate suite, including Postgres-backed tests,
simultaneously without sharing any mutable state — and the lane workflow documented in
DELEGATION.md ("Lanes, worktrees, and the merge queue") matches what actually works.

**Scope (minimal, no speculation)**
1. `scripts/lane_env.py` (new): `create <lane-id>` provisions a per-lane Postgres database
   (`jarvis_lane_<lane-id>`, on the existing local server) and registers a per-lane Temporal
   namespace (`lane-<lane-id>`), then prints the `.env` override block (JARVIS_DATABASE_URL,
   JARVIS_TEST_DATABASE_URL, JARVIS_TEMPORAL_NAMESPACE, API port). `destroy <lane-id>` drops
   them. Idempotent both ways; refuses to touch the default `jarvis` database or `default`
   namespace. Plain argparse + asyncpg + temporalio client — no new dependencies.
2. API port: if the API server/launcher hardcodes its port, add a settings field
   (`JARVIS_API_PORT`-style, default 8000) and use it in both topologies. If it is already
   configurable, say so and change nothing.
3. Postgres-backed test alignment (D-025.2): inventory every test that touches live Postgres
   (`test_budget_reservation_concurrency.py` already honors `JARVIS_TEST_DATABASE_URL` and the
   `postgres` marker — verify; check `test_denial_persistence.py` and any others). All of them:
   honor `JARVIS_TEST_DATABASE_URL`, carry the `postgres` marker, and **skip visibly** with a
   reason when the server is unreachable — a skip must never read as verified.
4. `.env.example`: document the three lane variables in a short "Development lanes" block.

**Out of scope**
Any change under `jarvis/` beyond the port setting. Docker compose changes. CI. The worktree
workflow docs (already amended). `docs/DECISIONS.md`.

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0 in your worktree; count before → after
- [ ] `uv run python scripts/lane_env.py create t1` then `create t2`, then the `postgres`-marked
      tests pass against lane t1's URL while a second run executes against t2's URL
      **at the same time** — state how you proved simultaneity
- [ ] `destroy` removes both lanes; the default `jarvis` DB and `default` namespace untouched
      (prove with a row-count/namespace check before/after)
- [ ] With Postgres stopped-or-unreachable simulated (e.g. a bogus URL), the marked tests skip
      with a visible reason and the suite still exits honestly

**Escalate instead of deciding if**
- Temporal namespace registration needs anything beyond the client API (server config, restart)
- The port cannot be made configurable without touching supervisor semantics (D-016/D-017)
- Any live test cannot honor an env URL without weakening what it asserts
