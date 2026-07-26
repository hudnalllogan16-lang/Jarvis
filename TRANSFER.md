# Moving this project to Claude Code

Three steps. Five minutes.

## 1. Get the files on disk

Download `jarvis-project.zip`, unzip it, and place the contents so that `pyproject.toml`
sits at the top level of your project directory:

```
D:\Projects\Jarvis\pyproject.toml     ✓ correct
D:\Projects\Jarvis\jarvis\pyproject.toml   ✗ nested one level too deep — move everything up
```

Confirm the hidden directory survived the unzip, because some tools skip dotfiles:

```powershell
dir D:\Projects\Jarvis\.claude\agents
```

You should see eleven `.md` files plus a README. If `.claude` is missing, your unzip tool
dropped it — re-extract with "show hidden files" enabled, or use `tar -xf jarvis-project.zip`.

## 2. Install

```powershell
cd D:\Projects\Jarvis
uv sync --all-extras
```

If `uv` isn't installed: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.

## 3. Start Claude Code

```powershell
claude
```

Then, as your first message:

Use the first-session prompt in [`KICKOFF.md`](KICKOFF.md) — copy it verbatim. It sets the
manager/implementer boundary, which is the thing most likely to drift in session one.

That's it. `CLAUDE.md` loads automatically into every session and every subagent. The roster
in `.claude/agents/` is discovered on startup. `scripts/gates.sh` runs as a `SubagentStop`
hook so no worker can report success over failing gates.

---

## What's in the box

| Path | What it is |
|---|---|
| `HANDOFF.md` | **Read first.** Project state, verified vs unverified, open items |
| `CLAUDE.md` | Ambient rules; loads into every agent automatically |
| `docs/DELEGATION.md` | The subagent roster, routing rubric, packet and report formats |
| `docs/packets/` | Five ready-to-run M6 work packets |
| `docs/DECISIONS.md` | D-001…D-017 and every defect finding — the project's memory |
| `docs/ROADMAP.md` | Milestone sequence and three revisions, with justifications |
| `docs/DEPENDENCIES.md` | Dependency graph, layering invariant, deferred-completion ledger |
| `.claude/agents/` | Eleven specialist subagents |
| `scripts/gates.sh` | Executable acceptance gates (exit 0 pass / 2 fail / 3 could-not-run) |
| `GETTING_STARTED.md` | For *using* Jarvis, not developing it |

## Expect the first session to be messy

The full test suite has never run — every prior session worked in a sandbox with no network
and no third-party packages. 229 tests are written; how many pass is genuinely unknown.
Packet M6-0 exists to find out, and it should be delegated rather than done by hand, because
it will produce a lot of error output that belongs in a worker's context instead of the
Manager's.

`HANDOFF.md` has the precise verified-versus-written breakdown. Read it before drawing
conclusions from a red test run.
