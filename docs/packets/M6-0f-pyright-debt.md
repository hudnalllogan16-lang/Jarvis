## Packet M6-0f: clear the first-ever pyright run's 97 errors

**Agent:** platform-engineer   **Model:** sonnet — annotation-level work, fully gate-covered
(395 green tests catch semantic drift; pyright itself gates the objective), reversible.

**Objective**
`bash scripts/gates.sh` exits 0 — the first fully green gate chain in this project's history —
with zero behaviour changes and zero gate weakening.

**Context you need**
This codebase was written across sessions with no interpreter and has never been type-checked.
Pyright now runs (gates reach it as of M6-0e) and reports 97 errors across
`jarvis/manager/activities.py`, `jarvis/persistence/engine.py`, `jarvis/registry/registry.py`,
`jarvis/runtime/worker.py`, `jarvis/shell/desktop.py`, `jarvis/shell/launcher.py`.

**Rules, in priority order**
1. Never change runtime behaviour to satisfy the checker. If the minimal type-correct change
   would alter behaviour, that error is a *finding* — report it, leave the code alone.
2. Never edit pyright's configuration to reduce strictness, and never delete code.
3. `# type: ignore`/`cast` are last resorts, allowed only for third-party typing limitations
   (e.g. Temporal/SQLAlchemy/pywebview stubs), each instance listed in your report with the
   library and reason. Prefer precise annotations, narrowing, and `assert x is not None`
   guards where the invariant is already guaranteed by construction — and say in a comment
   what guarantees it.
4. `jarvis/registry/registry.py:438` accesses `_source` (protected). If pyright flags it,
   understand why the audit payload reads it before deciding anything — if the access is
   deliberate, an explicit accessor or documented ignore may be right; propose in the report if
   unsure. Do not change what the audit payload contains.
5. `jarvis/shell/launcher.py:102` `health` is reportedly unused. Investigate whether it is
   genuinely dead or registered dynamically. If genuinely dead, that is a finding (possible
   missing wiring — the launcher is known-undertested), NOT a deletion.

**Acceptance criteria**
- [ ] `uv run pytest -q` → 395/395, unchanged
- [ ] `uv run pyright` (as gates.sh invokes it) → 0 errors
- [ ] `bash scripts/gates.sh` → exit 0, output quoted
- [ ] Report lists every ignore/cast with justification, and every finding under rules 1/4/5

**Out of scope**
Refactors beyond annotations/guards. New tests. Docs.

**Escalate instead of deciding if**
- A type error can only be resolved by changing a function's signature that other layers call
- A type error reveals a code path that cannot work at runtime (the RegistryError class of bug)
  — report it with the failing scenario; fixing it may need its own packet
- More than ~15 errors trace to one third-party library's stubs — stop and report before
  blanketing ignores
