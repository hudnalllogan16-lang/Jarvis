## Packet M6-0d: clear pre-existing lint/format debt so the gate chain runs end to end

**Agent:** refactorer   **Model:** sonnet — behaviour-preserving mechanical changes, fully
gate-covered (394 passing tests catch any semantic drift), trivially reversible.

**Objective**
`bash scripts/gates.sh` proceeds past the ruff-lint and format steps; every change is
behaviour-preserving; the full test suite still passes 394/394.

**Context you need**
M6-0 made the test gate pass for the first time, which means the lint/format/pyright steps in
`scripts/gates.sh` are now reachable for the first time. Known debt: 33 ruff errors (29
auto-fixable; includes unused imports and stale noqa comments in tests) and ~40 files failing
`ruff format --check`. None of this code has ever been linted or formatted by execution before.

**Files in scope**
Anything ruff or `ruff format` flags, in `jarvis/`, `tests/`, `scripts/`, `migrations/` — with
one exception below.

**Do NOT change**
- `jarvis/registry/registry.py` line ~151's undefined `RegistryError` (an F821). That is a real
  bug with its own packet (M6-0e); suppressing or "fixing" it mechanically would hide it. If the
  gate cannot pass with it present, add nothing — report how the gate treats it and stop.
- Any test's assertions or logic. Import/noqa/format cleanups only.
- Behaviour, anywhere. If a ruff fix would change semantics (e.g. an autofix that alters
  evaluation order), skip it and report it instead.

**Acceptance criteria**
- [ ] `uv run pytest -q` still 394/394
- [ ] `uv run ruff check` and `uv run ruff format --check` clean, except at most the M6-0e F821
- [ ] `bash scripts/gates.sh` — report the exit code and, if it now reaches pyright for the
      first time, report pyright's error count and the first ~10 errors verbatim; do NOT start
      fixing type errors (that's a separate decision)

**Out of scope**
Type-error fixes. The M6-0e bug. Any rename, restructure, or docstring rewrite ruff didn't ask for.

**Escalate instead of deciding if**
- An autofix would change behaviour and you can't make the mechanical change without it
- The format pass produces a diff in `jarvis/manager/workflow.py` that the determinism gate rejects
