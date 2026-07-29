# Packet P0-F — Deployment: service scripts, compose restart policy, the deployment document

Lane: `p0-f` · Branch: `lane/p0-f` · Owner: platform-engineer · Design authority:
`docs/design/OPERATIONAL-RUNTIME.md` Parts 6, 9.5, 11 (read them first; they bind).

## Mandate

Make the four deployment modes installable and documented. This packet is scripts, compose,
and docs only — **no runtime code changes**, and nothing in this packet touches the live
stack or the Docker daemon on this host. Installation itself happens later, in P0-G, on the
real host, by the Manager.

## Deliverables

1. **`scripts/install-service.ps1` + `scripts/uninstall-service.ps1`** — NSSM service
   install per design 6.1, exactly the recorded values: Application `<venv>\Scripts\
   jarvis-run.exe`, AppDirectory install root, AppExit Default Restart, AppThrottle 60000,
   AppRestartDelay 5000, AppStopMethodConsole 15000, AppStdout/AppStderr to
   `logs\jarvis-run.log` rotated at 10MB keep 10, delayed auto-start. Parameters for the
   NSSM binary path and install root; refuse with a clear message when either is missing
   or nssm.exe is not found (never download it in the script). Idempotent re-install
   (`nssm stop` + `remove confirm` if the service exists). PS 5.1-compatible.
2. **Compose (M10-F14):** `restart: unless-stopped` on `postgres`, `redis`, `temporal`,
   `temporal-ui`; new `jarvis` service running `jarvis-run` with `restart: unless-stopped`,
   `depends_on` the postgres healthcheck, its own healthcheck polling **`/api/ready`**, and
   `JARVIS_HEADLESS=1` in its environment.
3. **`docs/DEPLOYMENT.md`** — the one authority (design 6.4): the four-mode matrix (Part 6
   table); the NSSM procedure including the pinned NSSM version and a `<RECORD SHA-256 AT
   INSTALL>` placeholder the Manager fills at P0-G; the Task Scheduler fallback procedure
   with its limits stated honestly (restarts task on failure only, exit 0 stops, no stdout
   capture); exit codes 0/2/3 as the operator contract; the runbook basics (install, start,
   stop, logs, where `.env` lives). **Secrets (design 9.5):** `AppDirectory` + `.env` is
   the whole mechanism — the doc must say so and must NOT demonstrate `AppEnvironmentExtra`
   with a key in it.
4. **M10-F11 recorded as resolved by owner ruling (2026-07-28):** full unattended
   cold-boot recovery without user login is an **infrastructure decision, not an
   engineering deficiency** — it depends on Jarvis's eventual production environment
   (Windows native services, WSL2, dedicated server, NAS, cloud VM), which is evaluated in
   the next phase. The engineering obligation is complete: the service survives boot, the
   WAIT posture holds without crashing, and the runtime attaches the moment dependencies
   appear. Consequence stated plainly: V1/V3 are not measured on this host; on the current
   host, dependencies return at user login. List the candidate environments; do not pick.
5. **README.md / SETUP.md / GETTING_STARTED.md re-pointed** at DEPLOYMENT.md for topology —
   one authority, three pointers (design 6.4: "three documents restating one topology is
   how M10-F3 happened"). Remove any text naming the launcher as the supported autonomy
   topology.

## Boundaries

- No changes under `jarvis/` at all. Scripts, compose, docs only.
- Do not run docker/docker-compose against the live stack; compose changes are verified by
  `docker compose config` (parse-only) if available, else by YAML review in the report.
- No new actions or parameter rows (Part 7 was consumed by P0-B/C/D/E).

## Gates

`bash scripts/gates.sh` exit 0 in the worktree before reporting. Commit on `lane/p0-f`
only; never merge or push. Report 120/200 words: deliverables + how compose was verified +
gate result.
