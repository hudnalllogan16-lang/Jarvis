# Subagent roster

Operating manual: [`../../docs/DELEGATION.md`](../../docs/DELEGATION.md).

These are checked into version control deliberately — they are project infrastructure, and
improving a worker's system prompt is a durable improvement to the project rather than a
personal tweak.

Ambient rules for every agent live in `CLAUDE.md` at the repo root, which loads into each
one automatically. Do not duplicate those rules here; add task-specific context to the work
packet instead.

`.claude/settings.json` wires `scripts/gates.sh` as a `SubagentStop` hook so no worker can
report completion over failing gates.
