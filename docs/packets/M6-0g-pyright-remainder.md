## Packet M6-0g: clear the remaining pyright errors outside approvals/

**Agent:** platform-engineer   **Model:** sonnet — annotation-level, gate-covered, reversible.

**Objective**
`uv run pyright jarvis` reports 0 errors outside `jarvis/approvals/service.py` (which has its
own security-engineer packet, M6-0h — do not touch it), with zero behaviour changes.

**Context you need**
M6-0f cleared 26 of 97 first-ever pyright errors. Remaining, by cluster:
- `jarvis/api/app.py` (18) — `reportUnusedFunction` on route handlers defined inside the app
  factory; pyright doesn't model decorator registration. Same pattern already resolved in
  `jarvis/shell/launcher.py` (`health`) with a per-instance justified ignore.
- `jarvis/kernel/logging.py` (5), `kernel/container.py` (1), `kernel/runtime.py` (1),
  `jarvis/capabilities/queue.py` (1), `capabilities/contention.py` (1) — assorted, expected
  mechanical.
- `jarvis/llm/providers/anthropic.py` (10), `gemini.py` (16), `openai_compatible.py` (15) —
  never-executed provider code navigating untyped JSON/SDK surfaces.

**Rules (same as M6-0f, plus provider policy)**
1. Never change runtime behaviour to satisfy the checker; behaviour-changing "fixes" are
   findings, reported not made. Never reduce pyright strictness config. Never delete code.
2. Route handlers: per-instance `# pyright: ignore[reportUnusedFunction]` is pre-approved for
   decorator-registered handlers (Manager decision, following the launcher precedent). No
   file-level suppressions.
3. Provider cluster (Manager scoping decision, binding): prefer typing the JSON response paths
   actually read (small TypedDicts or explicit `isinstance` narrowing at the parse boundary);
   targeted `# pyright: ignore[...]` with a one-line reason where the gap is genuinely in
   third-party stubs. List every ignore in the report. **The anthropic provider is about to make
   this project's first live LLM call (M6-1): if any error there reveals a request/response
   shape that cannot work at runtime, that is a high-priority finding — report it prominently,
   do not paper over it.**

**Acceptance criteria**
- [ ] `uv run pytest -q` → 395/395, unchanged
- [ ] `uv run pyright jarvis` → only `jarvis/approvals/service.py` errors remain (expected 3)
- [ ] `bash scripts/gates.sh` exit code reported with the types-gate tail quoted
- [ ] Every ignore listed with reason; behaviour-change findings listed under rule 1

**Out of scope**
`jarvis/approvals/service.py` (M6-0h). New tests. Refactors beyond annotations/narrowing.

**Escalate instead of deciding if**
- A fix requires changing a signature other layers call
- An error reveals a runtime-impossible code path (RegistryError class of bug)
- The gemini/openai_compatible SDKs would need >10 ignores each even after typing the read
  paths — stop and report what a proper typing pass would take instead of blanketing
