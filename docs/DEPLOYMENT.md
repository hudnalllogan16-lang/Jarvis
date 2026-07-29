# Deploying Jarvis

This is the one authority on how Jarvis is deployed, supervised, and run unattended
(design [`docs/design/OPERATIONAL-RUNTIME.md`](design/OPERATIONAL-RUNTIME.md) Part 6, packet
`P0-F`). README.md, SETUP.md, and GETTING_STARTED.md point here for topology rather than
restating it — "three documents restating one topology is how M10-F3 happened" (design 6.4).

`jarvis-run` is the platform: the same four parts (API, worker, scheduler, Executive) the
desktop console runs, composed from the same part table under the same supervisor
(`jarvis/shell/service.py`), with no window and no browser, ever. Every mode below runs it.

---

## The four deployment modes

| # | Mode | Command | Restart | Console | Autonomy | Status |
|---|---|---|---|---|---|---|
| 1 | **Windows service** | `jarvis-run` under NSSM | NSSM, throttled | browser or the desktop app, attaching | full | **primary** |
| 2 | **Containers** | `jarvis-run` in compose | `restart: unless-stopped` | browser | full | supported |
| 3 | **Desktop console** | `jarvis` | Tier 1 (in-process) only | native window | full **while open** | development + operator |
| 4 | **Console-only attach** | `python -m jarvis.api.server` | none | browser | **none, and it says so** | supported |

Mode 4 is not a degraded Mode 1 — it's a read surface for a runtime hosted elsewhere. The
`runtime` and `workers` components on `/api/health` make that legible under every mode,
including this one.

When a runtime is already serving `api_port` on the same host (Mode 1 or 2), the desktop
console (Mode 3) **attaches** to it instead of starting a second one — it probes the port
first, and if it answers, it opens the window onto the existing runtime and starts no parts of
its own. Closing that window is then a no-op for the platform.

---

## Mode 1 — Windows service (NSSM), the primary mode

Windows is the deployment host of record. `jarvis-run` runs as a real Windows service — starts
at boot, no logged-in user required, restarts on unexpected exit only (an operator-initiated
stop stays stopped).

### Choice of service wrapper

| Candidate | Verdict |
|---|---|
| **NSSM** | **Chosen.** Real service semantics; `AppThrottle` gives a genuine throttle rather than a hot loop; `AppStdout`/`AppStderr` solve log capture, otherwise unsolved for a Windows service; `AppStopMethodConsole` delivers a console event the process can drain on. Cost: a vendored third-party binary — pinned below, with its SHA-256 recorded at install. |
| Task Scheduler | **Fallback**, documented below, for environments that forbid third-party binaries. Strictly worse: see its limits stated honestly in its own section. |
| pywin32 in-process service | **Rejected.** Puts the restarter inside the thing being restarted. |
| `pythonw` + a Startup shortcut | **Rejected.** Session-bound — fails the "no logged-in user required" bar outright. |

### 1. Get NSSM

Pinned version: **NSSM 2.24** (the standard stable build), from <https://nssm.cc/download>.
Download the `win64` binary for a 64-bit host. Never let an install script fetch this for
you — `scripts/install-service.ps1` refuses to run if it can't find the binary you point it
at, and it never reaches out to the network itself.

Record the hash of the exact file you downloaded:

```powershell
Get-FileHash .\nssm.exe -Algorithm SHA256
```

**NSSM 2.24 SHA-256** (recorded at install, 2026-07-29): distribution zip
`727d1e42275c605e0f04aba98095c38a8e1e46def453cdffce42869428aa6743`; win64 binary
`f689ee9af94b00e9e3f0bb072b34caaf207f32dcb4f5782fc9ca351df9a06c97`; installed on this host
at `C:\Tools\nssm-2.24\win64\nssm.exe`.

### 1a. Application Control environments (M10-F36)

Windows Smart App Control (or WDAC) in enforcement may block unsigned venv shim
executables — including `pytest.exe` and, potentially, `jarvis-run.exe` — with os error
4551, on a per-file reputation basis. Observed live on the development host 2026-07-29:
enforcement began mid-day and blocked the pytest shim while sibling shims kept running;
regenerated shims (new hashes, no reputation) were blocked too. If `jarvis-run.exe` is
refused at service start, point the service at the signed interpreter instead — same
process, no shim:

```
nssm set JarvisRun Application <install root>\.venv\Scripts\python.exe
nssm set JarvisRun AppParameters "-c \"from jarvis.shell.service import serve_headless; serve_headless()\""
```

Do not weaken the machine's App Control policy to accommodate Jarvis; that is the
operator's security posture, not the platform's to change.

### 2. Deploy the code

Copy (or clone) the repository to its install root, then from that directory:

```powershell
uv sync --all-extras
cp .env.example .env      # then edit .env — see "Secrets" below
uv run alembic upgrade head
```

This produces `<install root>\.venv\Scripts\jarvis-run.exe`, the binary the service wraps.

### 3. Install the service

From an **elevated** (Administrator) PowerShell:

```powershell
.\scripts\install-service.ps1 -NssmPath C:\tools\nssm-2.24\win64\nssm.exe -InstallRoot D:\Jarvis
```

`-NssmPath` and `-InstallRoot` are both mandatory — the script refuses with a clear message if
either path doesn't exist, or if `<InstallRoot>\.venv\Scripts\jarvis-run.exe` hasn't been built
yet (run `uv sync --all-extras` first). Re-running the script against an already-installed
service is safe: it stops and removes the existing service (`nssm stop` + `nssm remove ...
confirm`) before reinstalling, so running it twice has the same effect as running it once.

The script sets exactly these NSSM values (design 6.1's normative table):

```
Application          <InstallRoot>\.venv\Scripts\jarvis-run.exe
AppDirectory          <InstallRoot>
AppExit Default       Restart
AppThrottle           60000    (ms; below this counts as a failed start)
AppRestartDelay       5000     (ms)
AppStopMethodConsole  15000    (ms; matches the 15s drain budget)
AppStdout / AppStderr <InstallRoot>\logs\jarvis-run.log, rotate at 10MB
Start                 SERVICE_AUTO_START (delayed)
```

**On "rotate at 10MB, keep 10":** NSSM rotates a log by renaming it with a timestamp once it
crosses `AppRotateBytes` — it has no native setting that caps the *number* of rotated files it
keeps. `install-service.ps1` sets the 10MB threshold (`AppRotateBytes=10485760`,
`AppRotateOnline=1`, `AppRotateFiles=1`); capping retention at 10 files is an operator
housekeeping task (a periodic prune of `<InstallRoot>\logs\`), not something `nssm.exe set` can
express. Stated plainly rather than silently overclaimed.

### 4. Start it and verify

```powershell
& C:\tools\nssm-2.24\win64\nssm.exe start JarvisRun
curl http://localhost:8000/api/ready     # 200 once DB is reachable, schema is at head, and every part is RUNNING
```

### 5. Uninstall

```powershell
.\scripts\uninstall-service.ps1 -NssmPath C:\tools\nssm-2.24\win64\nssm.exe
```

Idempotent: running it against a service that isn't installed prints a message and exits 0.
Logs and `.env` under the install root are left in place.

### Task Scheduler fallback

For environments that forbid third-party binaries. Built into Windows, can run at boot as
`SYSTEM`, no download. **Its limits, stated honestly rather than left to be discovered:**

- It restarts a **task**, not a service — the distinction matters because it only reacts to
  the task ending, not to genuine liveness.
- It treats **exit code 0 as success and stops** — that happens to be correct for our exit-code
  contract (below), but only by construction, not because Task Scheduler understands it.
- **No usable stdout/stderr capture.** `jarvis-run`'s own log output still needs somewhere to
  go; without NSSM's `AppStdout`/`AppStderr`, you must redirect it yourself (e.g. wrap the
  command in a small `.cmd` that pipes to a file) or rely entirely on the application's own
  structured logging sink, if one is configured.

To configure: create a Basic Task, trigger **At startup**, action
`<InstallRoot>\.venv\Scripts\jarvis-run.exe`, "Run whether user is logged on or not", and under
Settings enable "If the task fails, restart every" with a delay (there is no equivalent of
`AppThrottle`, so pick a delay generous enough not to hot-loop on a bad configuration — a
throttle Task Scheduler cannot give you natively).

Adequate. Strictly worse than NSSM. Use it only where the third-party-binary constraint is
harder than the operational cost of these gaps.

### Secrets (design 9.5)

**`AppDirectory` plus `.env` is the whole mechanism.** The service's `AppDirectory` is set to
the install root; `jarvis-run` (via `pydantic-settings`) reads `.env` from that directory the
same way `uv run python -m jarvis` does in development. The service's own environment carries
no secret — `install-service.ps1` sets no `AppEnvironmentExtra` value, and it should not
acquire one. If a future change needs to hand the service a non-secret flag, it belongs in
`.env` or the service's own settings, not in `nssm set JarvisRun AppEnvironmentExtra
SOME_KEY=...` — that command is not demonstrated here, deliberately, because typing a secret
into a command line puts it in shell history and the Windows service registry in plaintext.

---

## Mode 2 — containers

`docker-compose.yml` now sets `restart: unless-stopped` on `postgres`, `redis`, `temporal`, and
`temporal-ui` (confirmed missing before this packet: `docker inspect` reported
`RestartPolicy.Name=no` on all four live containers — M10-F14). A `jarvis` service runs
`jarvis-run`:

```bash
docker compose up -d
docker compose ps          # jarvis should show healthy once /api/ready returns 200
```

- `restart: unless-stopped`, `depends_on` the `postgres` healthcheck (`condition:
  service_healthy`).
- Its own healthcheck polls **`/api/ready`** — not `/api/health`, which always answers 200 with
  a narrative body per D-016's degradation ladder and would tell Docker "send traffic" while
  explaining that nothing works. `/api/ready` is the endpoint built for exactly this: no
  narrative, 200 or 503.
- `JARVIS_HEADLESS=1` in its environment. `jarvis-run` never opens a window regardless, but the
  variable makes the intent explicit and is already honoured (`jarvis/shell/desktop.py:46`).
- Secrets follow the same rule as Mode 1: `env_file: [{path: .env, required: false}]` — the
  container reads the same `.env` you already created for local development, never a secret
  baked into the compose YAML. `required: false` lets `docker compose config` and a fresh
  checkout parse cleanly before `.env` exists; `jarvis-run` itself refuses to start (exit code
  3, below) if required settings are still missing.

**Known gap, flagged rather than papered over:** the `jarvis` service is defined with `build:
.`, and no `Dockerfile` exists in this repository yet. `docker compose config` parses and
resolves the build context without needing the `Dockerfile` to be present — which is how this
file's syntax was verified in this packet without touching the live stack — but an actual
`docker compose up --build` will fail until a `Dockerfile` is added. Writing one is packaging
work, not deployment-topology work, and is outside this packet's boundary (scripts, compose,
and docs only, no `jarvis/` changes); it's the natural next small packet for Mode 2 to become
buildable in practice.

---

## Mode 3 — desktop console

`uv run python -m jarvis`. Unchanged in behaviour, changed in status: it's the developer
experience and the operator's local console, not the supported unattended topology — that's
Mode 1 or 2, above. See "attaches instead of competing" in the mode table's note.

## Mode 4 — console-only attach

`uv run python -m jarvis.api.server`. Starts the API and dashboard only — no worker, no
scheduler, no Executive. A legitimate read surface onto a runtime hosted elsewhere (Mode 1 or
2 on the same host, or reachable over the network), and it says so: the `runtime` and `workers`
health components read from shared facts (the heartbeat table and Temporal's own poller count),
not from this process's own state, so an attach-only process reports accurately even though it
started nothing.

---

## Exit codes — the operator contract

`jarvis-run` (and by extension the service wrapping it) uses three exit codes as the interface
between the in-process Supervisor (Tier 1: restarts a *part*) and whatever restarts the
*process* (Tier 2: NSSM, `restart: unless-stopped`, or Task Scheduler):

| Code | Meaning | What the process supervisor should do |
|---|---|---|
| **0** | Clean stop — operator-requested (service control, Ctrl-C, SIGTERM/SIGBREAK) | **Not** restart |
| **2** | A dependency was unavailable past the `WAIT` posture's own patience | Restart, throttled |
| **3** | Configuration cannot become valid (`Settings()` refused, or the installation root is unresolvable) | Restart, throttled — the throttle *is* the alarm; an escalating gap between restarts is the visible signal |

NSSM's `AppExit Default Restart` combined with `AppThrottle 60000` implements this correctly
without needing to inspect the exit code itself: NSSM already treats any exit as "unexpected"
unless the service is being stopped through the Service Control Manager, which is exactly what
code 0 corresponds to.

---

## Runbook

**Install:** see Mode 1 (service) or Mode 2 (containers) above.

**Start:**
```powershell
& <NssmPath> start JarvisRun        # Mode 1
docker compose up -d jarvis         # Mode 2
```

**Stop:**
```powershell
& <NssmPath> stop JarvisRun         # Mode 1 — clean stop, exit code 0, no restart
docker compose stop jarvis          # Mode 2
```

**Logs:**
```powershell
Get-Content <InstallRoot>\logs\jarvis-run.log -Tail 100 -Wait   # Mode 1
docker compose logs -f jarvis                                   # Mode 2
```

**Where `.env` lives:** `<InstallRoot>\.env` for Mode 1 (read via `AppDirectory`); the repo
root's `.env` for Mode 2 (read via `env_file`, not baked into the image). It is gitignored in
both cases and must be created from `.env.example` before first start — see SETUP.md.

**Health vs. readiness while operating:**
- `/api/health` — the operator's narrative page. Always 200; explains what's degraded.
- `/api/ready` — what the service throttle and the container healthcheck actually consume.
  200 only when the database is reachable, the schema is at head, builtin types are installed,
  and (for a process running parts) every part is `RUNNING`.

---

## M10-F11 — cold-boot recovery without user login

**Resolved by owner ruling (2026-07-28), recorded in `docs/DECISIONS.md`:** full unattended
cold-boot recovery without a user login is an **infrastructure decision, not an engineering
deficiency.** It depends on Jarvis's eventual production environment, which is
deployment-architecture evaluation scoped to the **next phase** — this document does not pick
one.

**The engineering obligation is complete as of this packet and P0-A/B/D/E before it:** the
service survives a boot (NSSM's `Start SERVICE_AUTO_START`, delayed); the `WAIT` posture holds
without crashing — `bootstrap` retries preflight every 5 seconds indefinitely rather than
exiting, logging what it's waiting for; and the runtime attaches to its dependencies the moment
they appear, with no restart and no manual step required.

**The consequence, stated plainly:** Docker Desktop on Windows is a per-user application. A
`LocalSystem` service starting at boot will find Postgres, Redis, and Temporal unreachable
until a user logs in and Docker Desktop starts. On **this host**, in its current configuration:

- **V1** (log the session out entirely, wait for pollers) and **V3** (reboot recovery) from
  design Part 8's validation matrix are **not measured** here — they depend on exactly the
  infrastructure choice this ruling defers.
- **Dependencies return at user login**, not at boot. Between a cold boot and the next login,
  the service is up and waiting (per the `WAIT` posture) but not yet serving, because Postgres,
  Redis, and Temporal are not yet reachable.

**Candidate production environments** (evaluated next phase; none chosen here):

- **Windows native services** — Postgres and Temporal each run as their own Windows service
  (or Temporal via a second NSSM-wrapped binary) instead of inside Docker Desktop, removing the
  per-user dependency entirely.
- **WSL2** — a Linux environment under Windows where `restart: unless-stopped` runs under a
  real daemon, making the per-user question a non-issue the way it already is on Linux.
- **A dedicated server** — a machine whose only job is running Jarvis, with no interactive user
  session in the loop at all.
- **NAS** — a small always-on box already designed to run Docker workloads unattended.
- **Cloud VM** — infrastructure where "a user logs in" was never part of the boot sequence to
  begin with.

Whichever is chosen, `docker compose up -d` under `restart: unless-stopped` (Mode 2) already
resolves the per-user question on that target the same way it does today on Linux — Mode 2 is
unaffected by the M10-F11 escalation. It's Mode 1 specifically, and only on a host where the
container runtime itself is session-bound, that this question applies.

---

## Verification of this document's own claims

Compose changes were verified with `docker compose config` (parse-only — installed here as
Docker Compose v5.3.1) rather than by starting anything: the file parses, the `postgres`
healthcheck dependency and `jarvis` service resolve correctly, and the (initially failing)
`env_file: .env` reference was corrected to `{path: .env, required: false}` after `docker
compose config` demonstrated a fresh checkout without `.env` yet would otherwise fail to parse
at all — the fix was made **because** the parse-only check caught a real defect, which is the
point of running it. No container was started, and the live stack on this host was not touched.

`scripts/install-service.ps1` and `scripts/uninstall-service.ps1` were verified for syntax with
`[System.Management.Automation.Language.Parser]::ParseFile`, PowerShell 5.1's own parser. They
were not run against a live NSSM install in this packet — installation is packet `P0-G`'s, on
the real host, by the Manager, per this document's own Mode 1 procedure.
