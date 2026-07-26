## Packet M6-0e: fix the last three ruff findings for real (no suppressions)

**Agent:** platform-engineer   **Model:** sonnet — small, well-localised fixes; the suite
(394 green) plus the supervisor tests gate the risky part; escalation triggers named.

**Objective**
`uv run ruff check jarvis tests` is clean with zero `# noqa` additions, the suite still passes,
and `bash scripts/gates.sh` proceeds past ruff for the first time — reporting pyright's true
state verbatim.

**Part 1 — `jarvis/registry/registry.py` ~line 151: undefined `RegistryError` (F821)**
`set_type_enabled` on an uninstalled type raises `RegistryError`, which is never defined or
imported anywhere — the real runtime behaviour today is `NameError`. Fix by defining the
error properly: look at how this module's other errors are defined (e.g. `BusinessNotFoundError`)
and where they live; follow that pattern. Check what callers and docstrings expect. Add a
regression test in `tests/test_registry.py` whose docstring names this finding (M6-F3): calling
`set_type_enabled` for an uninstalled type raises the documented error, not `NameError`.

**Part 2 — `jarvis/shell/launcher.py`: two async findings**
- ~line 71, ASYNC240: `Path(...).exists()` called in an async function. Move the blocking check
  out of the event loop (e.g. `await asyncio.to_thread(...)`) or restructure so the check runs
  before the loop starts — whichever is smaller and clearer in context.
- ~line 148, ASYNC110: `while not stop.is_set(): await asyncio.sleep(0.25)` polling a
  `threading.Event`. Replace the poll with a real wait (e.g. `await asyncio.to_thread(stop.wait)`
  or an `asyncio.Event` set from the thread side via `call_soon_threadsafe`) — preserve exact
  shutdown semantics: whatever currently causes the loop to exit must still cause exit, with no
  new hang on shutdown.

The shell is topology, not architecture (D-016/D-017): do not move responsibilities between
supervisor/window/subsystems while fixing this.

**Acceptance criteria**
- [ ] `uv run ruff check jarvis tests` → 0 errors; `git`-visible diff contains no new `noqa`
- [ ] `uv run pytest -q` → 395/395 (394 + the new regression test); supervisor/shell tests untouched and green
- [ ] `bash scripts/gates.sh` — exact exit code; if pyright runs for the first time, report its
      total error count and the first ~10 errors verbatim. Do NOT fix type errors.

**Out of scope**
Pyright fixes. The launcher's alembic relative-path hardening (known, separately tracked).
Any supervisor restructure.

**Escalate instead of deciding if**
- The correct error type for Part 1 is ambiguous (two plausible homes/parents) — propose, don't pick
- Preserving shutdown semantics in Part 2 requires touching `jarvis/shell/supervisor.py`
- Any fix requires a new package or import that the layering gate rejects
