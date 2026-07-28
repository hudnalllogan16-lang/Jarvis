# Setting up Jarvis on a personal machine

## The short version

```bash
uv sync --all-extras            # add --extra desktop for a native app window
cp .env.example .env      # set JARVIS_LLM__MODEL and JARVIS_LLM__API_KEY
uv run python -m jarvis
```

That one command runs preflight, starts the Docker services if they aren't up, applies
migrations, installs the built-in company templates, and serves everything — dashboard at
<http://localhost:8000>. If something is missing it says so in plain language and starts what it
can: no database means it stops and tells you; no workflow runtime means the dashboard runs with
a banner saying companies can't act, and the worker attaches by itself when the runtime comes up.

Everything below is the long version — useful when the short one hits a snag, and for running the
pieces separately the way production does.


Target: a working local install where the test suite passes, migrations apply, and the Temporal
worker connects. Roughly 15 minutes, most of it Docker pulling images.

**Read this first:** this repository has never been run end to end. It was built in an
environment with no network access, so no dependency was ever installed and no test was ever
executed against a real database. Syntax, logic, and the dependency-free suites were verified;
everything requiring PostgreSQL, Temporal, or the installed packages was not. Expect to hit
something on first run. Step 6 tells you how to read the failures.

---

## Step 0 — Prerequisites

You need three things: **Python 3.14+**, **uv**, and **Docker**.

```bash
python3 --version        # need 3.14 or newer
docker --version
docker compose version   # must be the plugin form, not docker-compose
uv --version
```

**Install uv** if missing:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows PowerShell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Python 3.14** — you don't need it system-wide. uv can fetch it:

```bash
uv python install 3.14
```

**Docker** must be running before Step 2. On macOS/Windows that means Docker Desktop is open. On
Linux, `sudo systemctl start docker`.

You'll want about 4 GB free for the images and 2 GB of RAM available — Temporal's auto-setup
image is the heavy one.

---

## Step 1 — Get the code and install dependencies

```bash
cd jarvis
uv sync --all-extras            # add --extra desktop for a native app window
```

`--all-extras` matters: it pulls the dev group, which includes `pytest`, `ruff`, `pyright`, and
`aiosqlite`. Without it the test suite can't run — the tests use in-memory SQLite so they need no
database.

This creates `.venv/`. You never activate it; `uv run` handles that.

**Verify:**

```bash
uv run python -c "import temporalio, sqlalchemy, pydantic; print('deps ok')"
```

---

## Step 2 — Configure

```bash
cp .env.example .env
```

Open `.env` and set exactly two values:

```bash
JARVIS_LLM__PROVIDER=anthropic          # or openai, gemini, kimi, ollama, openrouter, lmstudio
JARVIS_LLM__MODEL=<your-model-id>       # required, no default anywhere in the codebase
JARVIS_LLM__API_KEY=<your-key>          # not needed for ollama or lmstudio
```

The double underscore is the nesting delimiter — `JARVIS_LLM__MODEL` maps to `settings.llm.model`.
A single underscore will be ignored.

No model identifier is hardcoded anywhere in Jarvis, deliberately. Model names get renamed and
retired; pinning one in source turns that into a code change. Check your provider's current
documentation for the model string.

**Running fully local?** Set `JARVIS_LLM__PROVIDER=ollama` and leave the API key blank. Ollama's
default base URL (`http://localhost:11434/v1`) is already configured, and local providers skip
the API-key requirement by design.

`.env` is gitignored. Keep it that way.

---

## Step 3 — Start the services

```bash
docker compose up -d
```

This starts four containers: PostgreSQL 17, Redis 7, Temporal, and the Temporal web UI.

```bash
docker compose ps      # all should show running / healthy
```

Give Temporal 30–60 seconds on first start — `auto-setup` creates its own databases inside the
same PostgreSQL instance before it accepts connections. If `temporal` shows as restarting,
that's usually still in progress. Watch it:

```bash
docker compose logs -f temporal
```

Wait for it to stop churning, then Ctrl-C.

**Image pins:** the compose file pins `temporalio/auto-setup:1.25` and `temporalio/ui:2.31.2`.
If either tag no longer exists, check Docker Hub for a current tag and update `docker-compose.yml`
— nothing in Jarvis depends on those specific versions.

**Verify:**

```bash
docker compose exec postgres psql -U jarvis -d jarvis -c '\l'   # lists databases
open http://localhost:8233                                       # Temporal UI
```

---

## Step 4 — Apply migrations

```bash
uv run alembic upgrade head
```

This applies `0001_kernel_foundation` (registry, audit log, decision log) and
`0002_execution_spine` (events, dedup, budget ledger, idempotency, dead letters).

Migrations read `JARVIS_DATABASE_URL` directly and deliberately do not build a full config object
— applying a schema has nothing to do with which LLM you configured, so `alembic upgrade` works
before you've set an API key.

**Verify the nine tables exist:**

```bash
docker compose exec postgres psql -U jarvis -d jarvis -c '\dt'
```

Expect: `alembic_version`, `audit_log`, `budget_ledger`, `business_instances`, `business_types`,
`dead_letters`, `decision_log`, `event_consumptions`, `events`, `idempotency_keys`.

**Confirm the migration round-trips** — a migration that can't be undone is a migration you can't
safely deploy:

```bash
uv run alembic downgrade base && uv run alembic upgrade head
```

---

## Step 5 — Run the tests

The suite uses in-memory SQLite, so it needs nothing from Step 3.

```bash
uv run pytest -q
```

125 tests. Start with the dependency-free ones if you want a fast signal — these exercise the
state machine, contention policy, and identity derivation with no database at all:

```bash
uv run pytest -q tests/test_lifecycle.py tests/test_logging_redaction.py \
                 tests/test_fair_queue.py tests/test_runtime_identity_boundary.py
```

Then the security boundary, which is the suite that matters most:

```bash
uv run pytest -q tests/test_registry.py -v
```

These assert that a request cannot claim another business's identity, cannot escalate tool or
credential scope, cannot invoke an unpermitted capability, and cannot dispatch to a paused
company — and that every one of those rejections writes an audit record. **If one of these fails,
stop and investigate rather than adjusting the test.** They encode spec §10.

Lint and types:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Pyright runs in strict mode over `jarvis/`. It has never been executed, so expect findings — most
likely around SQLAlchemy's typing and the Temporal decorators.

---

## Step 6 — Open the dashboard

```bash
uv run python -m jarvis.api.server
```

Then open <http://localhost:8000>.

You'll see an empty state: "No companies yet" — because none have been created in this
database yet, not because the feature doesn't exist (companies have existed since Milestone 4/5).
The page is doing real work regardless: it polls for anything needing your OK, and the top strip
shows spending against your daily limit.

Note this step runs `jarvis.api.server` on its own: API and dashboard only, no worker, no
scheduler, no Executive. A company created here reaches "running" but nothing will ever wake it
up — that requires Step 7 below, or (the supported way to run Jarvis day to day) `uv run python
-m jarvis` in place of Steps 6 and 7 combined, which supervises all of it in one process.

The API is browsable at <http://localhost:8000/api/docs> if you want to poke at it directly.

Leave this running in its own terminal.

---

## Step 7 — Start the worker

```bash
uv run python -m jarvis.runtime.worker
```

Expected output: a JSON log line saying `kernel initialised`, then `worker starting`. Then, if you
have no companies yet, quiet — this process also runs the scheduler sweep and the Executive tick
(§9 timers, D-041), so it is not idle, it simply has nothing to do yet. Create a company through
the Step 6 dashboard while this is running and it reaches `ACTIVE`, the next sweep starts its
Business Manager workflow within seconds, and it runs on its own from there.

This topology (worker + scheduler + Executive as a bare `asyncio.gather`, no process supervision
— see `docs/reports/RUNTIME-AUDIT.md` M10-F6/F7) is not the supported way to run Jarvis
unattended; a crash here does not restart itself. `uv run python -m jarvis` runs the same three
loops, plus the API, under one supervisor that does restart crashed parts.

Confirm it registered at http://localhost:8233 under the `jarvis-platform` task queue.

Ctrl-C to stop.

---

## Step 8 — Kernel smoke test

Proves configuration, database, and the DI container work together:

```bash
uv run python -c "
import asyncio
from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel

async def main():
    kernel = PlatformKernel(Settings())
    async with kernel.services() as svc:
        print('installed business types:', await svc.registry.installed_types())
    await kernel.aclose()

asyncio.run(main())
"
```

Expect `installed business types: []`. An empty list is success — no business types exist until
Milestone 4.

---

## Troubleshooting

**`ValidationError: llm.model — String should have at least 1 character`**
`JARVIS_LLM__MODEL` isn't set, or you used a single underscore. Check `.env` and confirm you're
running from the repo root, since pydantic-settings reads `.env` relative to the working
directory.

**`ConfigurationError: provider <x> requires JARVIS_LLM__API_KEY`**
Working as intended. Set the key, or switch to `ollama`/`lmstudio` which don't need one.

**`connection refused` on port 5432 or 7233**
Services aren't up. `docker compose ps`. If Temporal is restarting, give it another minute — see
Step 3.

**`asyncpg.exceptions.InvalidCatalogNameError`**
The `jarvis` database doesn't exist. Usually means Postgres initialised before the environment
was set. Nuclear option: `docker compose down -v` (this deletes the volume) then `up -d` again.

**Tests fail with `ModuleNotFoundError: aiosqlite`**
You ran `uv sync` without `--all-extras`.

**`pytest` collects zero tests**
Run from the repo root. `testpaths = ["tests"]` is relative.

**Temporal UI is blank**
It's on **8233**, not 8080 — the compose file remaps it to avoid colliding with anything else you
might have on 8080.

---

## What you can and can't do yet

**Can:** create companies, watch their health, approve or deny what they ask for, pause and start
them, read what they did and why, and drill into full detail when you want it. The budget
hierarchy refuses spend that would breach a ceiling, and the autonomy ladder graduates routine
actions after a clean streak — with an easy undo.

**Can, as of Milestone 4/5 (the current repo is at Milestone 9):** run a company autonomously —
the Business Manager and scheduler wake it up on its own, on the Manager's own Temporal timer,
with no action from you required. This requires running the worker/scheduler (Step 7) or the
launcher (`uv run python -m jarvis`) — `jarvis.api.server` alone (Step 6) does not start them,
so a company created under that process alone will sit `ACTIVE` and never act.

**Genuinely can't yet:** trade live (Trading Analysis ships in a later milestone), and a few G2/G3
governance mechanisms are recorded deferrals — see `docs/reports/M9.md`.

---

## Daily commands

```bash
docker compose up -d                    # start services
docker compose down                     # stop (keeps data)
docker compose down -v                  # stop and wipe data
uv run pytest -q                        # tests
uv run alembic upgrade head             # apply migrations
uv run python -m jarvis                  # supported topology: everything, one process, supervised
uv run python -m jarvis.api.server       # dashboard only — read-only, no autonomy (no worker/scheduler)
uv run python -m jarvis.runtime.worker  # worker + scheduler + executive, unsupervised (no auto-restart)
docker compose logs -f temporal         # tail Temporal
```
