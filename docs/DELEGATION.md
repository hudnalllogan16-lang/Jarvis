# Delegation Model

How Jarvis is built: an Engineering Manager owns architecture, decisions, and project
memory; specialist subagents implement. This document is the operating manual for that
split — the roster, how work is routed, what a work packet contains, and what comes back.

Companion to `ROADMAP.md` (sequence), `DECISIONS.md` (why), and `DEPENDENCIES.md` (what
depends on what). Those three are the Manager's memory and are **not** editable by workers.

---

## Why delegate at all

The obvious reason is cost: a Sonnet worker is cheaper than an Opus one. That reason is
real but secondary.

The primary reason is **context integrity**. A subagent runs in its own context window;
its file reads, failed attempts, test output, and exploratory greps stay there, and only
its final report returns to the Manager. Over a project this long, that is the difference
between a Manager that still holds the whole architecture coherently at milestone 11 and
one whose context is two-thirds spent on tool output from milestone 4.

Every rule below is chosen to protect that: bounded reports, read-only researchers, audits
that return verdicts instead of code, and a standing prohibition on the Manager reading
worker-modified files for routine work.

---

## Layers, and where the boundary sits

```
Owner ─── holds the Architecture Specification. Amendments are the owner's alone.
  │
Engineering Manager (Fable) ─── roadmap · architecture · decisions · project memory
  │                             DECOMPOSES work into packets · REVIEWS · MERGES
  │
  ├──► architecture-auditor ────── "is it correct?"  · reports directly to the Manager
  ├──► product-reviewer ────────── "is it delightful?" · reports directly to the Manager
  ├──► spec-archaeologist ──────── read-only research, so recall costs 200 words not 2,000
  │
  └──► delivery-coordinator ────── EXECUTES prepared packets · drives gate retries
         │                         cannot edit · cannot decide · cannot rewrite a packet
         ├── platform-engineer
         ├── workflow-engineer
         ├── data-engineer
         ├── security-engineer
         ├── operator-surface-engineer
         ├── business-type-author
         ├── test-engineer
         ├── docs-writer
         └── refactorer
```

Requires `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH: "2"`, set in `.claude/settings.json`, since
subagents cannot spawn subagents by default.

### The one boundary that matters: decomposition is not coordination

**Decomposition stays with the Manager. Permanently.** Deciding how a milestone splits, what
each packet may and may not touch, and which model each needs is the highest-value
architectural work in this system. It requires holding the specification, every numbered
decision, and every prior finding simultaneously. Anything cheap enough to be worth delegating
cannot hold that; anything that can hold it costs Manager prices. Delegating decomposition
doesn't save money — it produces packets that are subtly wrong in the exact way only the
Manager could have caught.

Worked example: `docs/packets/M6-1-finance-type.md` forbids editing the generic machinery, so
that D-014 gets *tested* rather than worked around, and states that being blocked is a useful
result. That constraint is the entire point of the packet, and it comes from knowing why D-014
exists. A coordinator writing that packet would have written "add the Finance type."

**Coordination is delegated, because it is mechanical.** Dispatching a written packet, running
gates, bouncing a worker on a gate failure with the failure text, re-running, consolidating
reports — none of it needs project memory, and the retry loop in particular generates exactly
the kind of error output this architecture exists to keep out of the Manager's context.

### Two rules that keep the layer from becoming a bottleneck

1. **Escalations pass through verbatim.** The coordinator forwards a worker's escalation block
   unedited and stops dispatching. It never answers one. An escalation is a request for an
   architectural decision, and its value is entirely in its specifics — M5-F5 was diagnosable
   only because the report carried exact `curl` output and the precise point the log stopped.
   Summarised twice, that becomes "dashboard doesn't start" and the root cause stays hidden.
2. **The auditor never sits under the coordinator.** It is the Manager's instrument for
   deciding whether to merge. A coordinator that owned the auditor would decide what the
   Manager hears about compliance, which makes the review theatre. **The product-reviewer sits
   in the same place for the same reason** — it reports experience findings straight to the
   Manager, never filtered through execution.

### Two kinds of review, both gating

Correctness and experience are different questions, and a milestone can pass one while failing
the other. So there are two independent reviewers, each reporting directly to the Manager:

| | `architecture-auditor` | `product-reviewer` |
|---|---|---|
| Asks | Is the system correct? | Is it delightful to operate? |
| Reads | The diff, against spec and decisions | The running operator surfaces |
| Gates | Any milestone touching architecture | Any milestone with an operator-facing surface |
| Verdict | MERGE / REVISE / ESCALATE | SHIP / REVISE |

A milestone with both an architectural and an operator-facing surface needs **both** verdicts
before it is complete. The product reviewer's constitution is `docs/PRODUCT.md`; it judges
whether work moves toward the premium-desktop objective, not whether it has arrived there —
the prototype UI is allowed to look plain, but not to confuse or dead-end. Neither reviewer
edits code or makes implementation decisions; both exist so the Manager decides on independent
evidence.

### When to skip the coordinator

Delegate straight to a worker when there is **one** packet, when the work is Tier C (the
Manager is reading the code anyway, so a middle layer only adds paraphrase), or when the
packet is likely to escalate — routing a probable escalation through a layer whose only
correct move is to forward it adds latency for nothing.

Use the coordinator for **two or more prepared packets that can run without further
architectural decisions.** M6-0 through M6-3 is a good candidate; M6-4 (the audit) is not, and
is excluded by the coordinator's own instructions.

**A caveat on tool restriction:** the `Agent(type1, type2)` allowlist syntax does not constrain
a subagent — in a subagent definition any type list inside the parentheses is ignored. The
coordinator's restriction to named-in-packet agents is therefore enforced by its system prompt
rather than by configuration. Treat a coordinator that spawns an agent no packet named as a
defect in its prompt, and tighten it.

## The roster

Eleven agents. Specialisation is justified only where an agent needs *different knowledge*,
*different tool access*, or *a different model tier* — otherwise it would be a duplicate
with a new name, and overlapping descriptions cause misrouting.

### Implementers

| Agent | Territory | Default model |
|---|---|---|
| `platform-engineer` | Backend services, registry, API routes, KPI, notifications, scheduler, shell. **The default.** | Sonnet |
| `workflow-engineer` | Temporal workflows and activities, determinism, concurrency, async coordination | Opus |
| `data-engineer` | Models, migrations, indexes, session scoping | Sonnet |
| `security-engineer` | Credentials, scopes, identity, approval gating, budget enforcement, idempotency | Opus |
| `operator-surface-engineer` | Dashboard markup, operator copy, §12.5 compliance | Sonnet |
| `business-type-author` | Business type definitions — pure configuration (D-014) | Sonnet |
| `test-engineer` | Test suites, executable gates, fixtures | Sonnet |
| `docs-writer` | User and developer documentation, docstring passes | Haiku |
| `refactorer` | Behaviour-preserving changes only | Sonnet |

### Reviewers — read-only, and the main context savings

| Agent | Purpose | Default model |
|---|---|---|
| `delivery-coordinator` | Executes prepared packets, drives gate retries, consolidates reports. No edit tools, no decisions. | Sonnet |
| `architecture-auditor` | Reads the diff, audits against spec and decisions, returns a merge verdict | Opus |
| `product-reviewer` | Reviews the operator experience, returns a ship verdict | Opus |
| `spec-archaeologist` | Answers "what have we already decided about X" from project memory | Sonnet |

`architecture-auditor` is the highest-leverage agent in the roster. It spends Opus tokens
reading a diff so the Manager can spend a few hundred tokens reading a verdict. On Tier C
work the Manager still reads the code; on Tier B it should not need to.

`spec-archaeologist` exists so that recalling a decision costs a 200-word answer instead of
re-reading `DECISIONS.md` into the Manager's context. Use it before writing any packet whose
task touches a numbered decision.

### Enable on day one

`platform-engineer`, `test-engineer`, `architecture-auditor`, `spec-archaeologist`, plus
whichever specialist the current milestone needs (`business-type-author` for M6). The rest
activate as their territory comes up. Fewer live agents means sharper routing.

---

## Routing: model selection is not the same as tier

Tiers describe *task shape*. They are a useful first cut but a poor final answer, because
two tasks of identical shape can differ enormously in what a mistake costs.

| Tier | Shape | Typical agents |
|---|---|---|
| **A** | Documentation, comments, mechanical refactors, copy changes, configuration | `docs-writer`, `refactorer`, `business-type-author` |
| **B** | Normal feature implementation, unit and integration tests, new services and routes | `platform-engineer`, `test-engineer`, `data-engineer`, `operator-surface-engineer` |
| **C** | Concurrency, workflow engine, security, schema invariants, event semantics | `workflow-engineer`, `security-engineer`, `data-engineer` (schema), `architecture-auditor` |

### The rubric

Model choice is a judgement over four properties of the task, not a lookup from its tier.
Score each, then route. The rubric exists so the decision is reproducible and can be
revisited when model capabilities or pricing change.

**1. Gate coverage — the dominant factor.**
Is correctness *mechanically checkable* by something already in `scripts/gates.sh`?

- **Fully covered** → route cheaper by one step. A wrong answer fails a gate, the worker
  sees the failure, and it fixes itself before the Manager ever looks. Retries on a cheap
  model beat one attempt on an expensive one.
- **Partly covered** → route at tier default.
- **Not covered — correctness is a judgement** → route up. This is where reasoning depth
  actually buys something, because nothing but a good reviewer will catch a mistake.

This is the main economic lever in the system. Extending gate coverage is therefore not
just quality work; it makes future work cheaper. That is why `test-engineer` sits at
Tier B rather than being treated as overhead.

**2. Blast radius.** What does a plausible mistake do?

- Corrupts persisted data, leaks a secret, or lets an action bypass approval → **Opus, always.**
- Produces wrong behaviour that looks correct → Opus.
- Produces obviously broken behaviour → the gates catch it; cheaper is fine.
- Produces a cosmetic defect → cheapest capable.

**3. Reversal cost.** Trivially revertable (a doc, a template, an isolated module) tolerates
a cheaper model. Anything embedded in a migration chain, a persisted schema, or an
externally-visible contract does not.

**4. Simultaneous invariants.** Count the constraints that must hold *at once*. Writing a
business type holds one (data-only). Changing the Manager's cycle boundary holds five
(determinism, bounded state, continuation model, cost ceiling, wake-rate bound). Holding
many invariants simultaneously is precisely what higher reasoning capacity is for.

### Applying it

Frontmatter sets each agent's *default* model. The Manager overrides per invocation when
the rubric says otherwise — a per-invocation model parameter takes precedence over
frontmatter, and persists if the subagent is resumed. So:

- `data-engineer` defaults to Sonnet, but a task that changes a primary key or makes an
  append-only table mutable is invoked on Opus.
- `platform-engineer` defaults to Sonnet, but adding a route whose correctness no gate
  checks is invoked on Opus.
- `docs-writer` defaults to Haiku, but a getting-started rewrite that must not overclaim
  verification is invoked on Sonnet, because "is this claim true" is a judgement no gate
  covers.

State the routing decision in one line when delegating. A choice that can't be justified
in one line usually means the packet isn't decomposed enough yet.

---

## Ready-made packets

`docs/packets/` holds written packets for the current milestone, so a session can begin by
delegating rather than planning. M6 is fully packeted: `M6-0-bootstrap` (establish the real
test baseline) through `M6-4-audit`. Run M6-0 first — nothing else is trustworthy until the
suite has actually executed once.

Keep packets in the repo after they're done. A completed packet plus its report is the
clearest record of what a milestone actually involved, and it's the raw material for the
milestone report.

## The work packet

Workers start cold. A subagent doesn't see the Manager's conversation, and the only channel
into it is the prompt string — so a vague packet produces confident garbage. Precision here
is the single highest-return discipline in the whole system.

Note the division: **`CLAUDE.md` carries ambient rules** and loads into every worker
automatically, so packets never restate the invariants. **The packet carries task-specific
context** — including the text of any decision the task touches, quoted inline rather than
referenced, because a worker that has to go find `DECISIONS.md` will read all of it.

```markdown
## Packet <milestone>-<n>: <one-line objective>

**Agent:** <agent name>   **Model:** <model> — <one-line rubric justification>

**Objective**
One sentence. What must be true when this is done.

**Files in scope**
Explicit paths. Read these first:
- path/to/file.py — what it currently does
Create:
- path/to/new_file.py — what it should do

**Context you need**
The decisions and spec requirements that bear on this task, quoted, not referenced.
Nothing else — do not include background the task doesn't turn on.

**Acceptance criteria**
Executable wherever possible:
- [ ] `bash scripts/gates.sh` passes
- [ ] <specific new test> exists and passes
- [ ] <observable property> holds
Non-executable criteria are stated as questions the report must answer.

**Out of scope**
Explicit. Things you might reasonably think belong here and don't, with where they go.

**Escalate instead of deciding if**
- <named trigger>
- <named trigger>
```

The "escalate if" list is not boilerplate. Name the specific ambiguities the Manager
expects this task to hit. A worker that hits an unnamed ambiguity will guess.

---

## The implementation report

Bounded on purpose. An uncapped report puts the worker's context back into the Manager's
and defeats the point. **Target 300 words, hard cap 500.** Prose, not a file listing.

```markdown
## Changed
- path — what changed and why, one line each

## Decisions I did not make
Anything requiring an architectural or invariant judgement, with what I did instead
(usually: stopped, or implemented the conservative option and flagged it). "None" is
a valid and common answer.

## Gates
Output of `bash scripts/gates.sh`. Test count before → after.

## Verified vs written
What I executed. What I only wrote and could not run, and why.

## Follow-ups
Discrete tasks this work implies but does not include.
```

Two sections are load-bearing:

**"Decisions I did not make"** is how the escalation protocol produces project memory
rather than silence. It is also where the Manager finds the raw material for new D-entries.

**"Verified vs written"** exists because this project has been burned by the gap between
them (M5-F5 lived precisely there). A report that blurs the distinction is incomplete,
and the auditor is instructed to treat overclaimed verification as a finding.

---

## Escalation protocol

**Workers never make architectural decisions.** When a task requires one, the worker stops
and returns:

```markdown
## ESCALATION
**Blocked on:** what decision is needed, in one sentence.
**Why it's architectural:** which layer, responsibility, or invariant it would change.
**Options:** each with what it costs and what it forecloses.
**My recommendation:** which one and why — as a recommendation, not a decision.
**What I completed anyway:** the unblocked part, if any.
```

Triggers, spelled out in every worker's system prompt:

- A mechanism the architecture doesn't specify → needs a D-entry.
- A responsibility that would move between layers → architecture amendment.
- A new package, or a forward import → dependency graph change.
- A test and the code disagreeing → one is wrong; deciding which is the Manager's call.
- A security boundary that would widen.
- An invariant that would need weakening to make the task possible.

An escalation is a **successful** outcome, not a failure. A worker that guesses at an
architectural decision and proceeds has produced work that must be re-reviewed from
scratch; a worker that stops has produced a decision request the Manager can answer in a
paragraph. Say this in packets when a task looks likely to hit one.

---

## The execution record

Every coordinator run produces a machine-readable manifest at `docs/runs/<run-id>.json`
alongside the human-readable report. The report is for reading once; the manifest is for
querying later, so operational history stops competing with architecture for space in the
Manager's context.

**The manifest is generated, never authored.** `scripts/gates.sh` writes a record of each
gate outcome at the moment that gate runs; `scripts/manifest.py` assembles those records plus
git's view of the working tree into the manifest. The coordinator triggers the script and
cannot write the file — it has no Write tool.

This matters because a coordinator-authored manifest would be a structured self-report, which
is exactly what the coordinator itself is told not to accept from a worker claiming its gates
passed. Structure reads as authority; `"status": "success"` invites belief in a way a paragraph
does not. So the schema separates and labels two zones:

| Zone | Contents | Trust |
|---|---|---|
| `observed` | Gate outcomes, changed and added files, commit, branch | Cannot be forged. A failed gate cannot be recorded as a pass. |
| `declared` | Which packet went to which worker on which model, retry counts, escalation count | A coordinator claim, labelled as one. |

`status` is derived from observed facts and the escalation count only: `escalated` if anything
escalated, then `failed` if a gate failed, then `degraded` if a gate could not run, then
`success`. Degraded is a distinct status because a degraded run has verified nothing and must
never be mistaken for a pass — that conflation is the M5-F5 failure mode in a new form.

Query it with `scripts/runlog.py`, which labels the provenance of every answer:

| Command | Answers |
|---|---|
| `summary` | one line per run |
| `gates` | which gates fail or degrade most often *(observed)* |
| `rework` | which packets needed retries *(declared)* |
| `workers` | per-worker packet and retry rate *(declared)* |
| `touched <path>` | which runs changed a subsystem, and which workers were dispatched *(files observed, attribution declared)* |
| `escalations` | which runs escalated |

Escalation *text* is deliberately not in the manifest. Escalations reach the Manager verbatim
in the report; reducing one to a count would destroy the specifics that make it actionable,
which is the whole reason they pass through unedited.

On `workers`: a high retry rate almost always means packets to that worker are underspecified
rather than that the worker is weak. Read the packets before adjusting an agent prompt.

Manifests are committed — they are project memory. The transient gate records in
`.jarvis-run/` are gitignored and consumed on assembly.

## The Manager's context budget

Rules the Manager holds itself to, since nothing enforces them mechanically:

1. **Don't read worker-modified files on Tier A or B work.** Read the report and the
   auditor's verdict. If those are insufficient, the report format needs fixing — say so
   rather than compensating by reading the diff.
2. **Route research to `spec-archaeologist`.** Re-reading `DECISIONS.md` to recall a
   decision spends the exact resource this architecture exists to protect.
3. **One packet, one concern.** A packet that needs three agents is three packets. Compound
   packets come back as compound reports, which are long reports.
4. **Audit before reading.** On Tier C, the Manager reads the code — but after the auditor's
   verdict, so it knows where to look instead of reading everything.
5. **Distil, then discard.** A merged milestone's reports get compressed into
   `DECISIONS.md`, `DEPENDENCIES.md`, and the milestone report. The reports themselves are
   then dead weight; the distilled record is the memory.

---

## Review depth by tier

| Tier | Automatic gates | Auditor | Manager reads code |
|---|---|---|---|
| A | Yes | No | No — report only |
| B | Yes | Yes | Only if the auditor says REVISE or ESCALATE |
| C | Yes | Yes, always | Yes, always, after the verdict |
| Any escalation | — | — | Yes |
| Any security boundary | Yes | Yes | Yes, always |

"Automatic gates" means `scripts/gates.sh`, wired as a `Stop` hook in `.claude/settings.json`
so a worker cannot report completion over failing gates. That hook is the load-bearing part
of Tier A throughput: it makes cheap work safe without spending Manager attention on it.

---

## Lanes, worktrees, and the merge queue

Adopted with the sub-agent organization (`docs/reports/SUBAGENT-ORG.md`, D-026) after M6
measured what actually serialized development: the environment, not the files. Everything in
this section is process; nothing changes the architecture, the packet format, or the review
model above.

### The lane workflow

An implementation packet that edits code runs in its **own git worktree**, not the main
checkout:

```
git worktree add ../Jarvis-lanes/<packet-id> -b lane/<packet-id>
```

- The worker is pointed at the worktree as its project root and never sees the main checkout.
- The lane gets its own environment: `.env` copied from the main checkout, then overridden
  per-lane where the packet needs live services (see "Lane environments" below).
- `bash scripts/gates.sh` runs **in the worktree** before the worker reports; its `.jarvis-run/`
  records and pytest state are naturally isolated.
- Read-only agents (auditor, product-reviewer, spec-archaeologist) and docs-only packets do not
  need a lane; they run against the main checkout and are always parallel-safe.
- A lane that produced garbage is discarded with `git worktree remove --force` and costs
  `main` nothing. This replaces sequential caution as the failure-containment mechanism.

### Lane environments

Live-verification work parameterizes the shared local stack instead of assuming exclusive
ownership of it: a per-lane Postgres database (same server), a per-lane Temporal namespace,
and a per-lane API port, all set via the lane's `.env` (`JARVIS_DATABASE_URL`,
`JARVIS_TEMPORAL__NAMESPACE`, plus the API port variable). `scripts/lane_env.py` provisions and
tears these down. Postgres-backed tests must be marker-gated and skip *visibly* when the stack
is unreachable — a skip is reported, never counted as verified (D-025.2, M5-F5 discipline).

### The merge queue

**Only the Manager merges.** One lane at a time, in dependency order — data/migrations first,
security next, platform/workflow, surface, docs last — so the riskiest changes land earliest
and reviews see final state.

1. Lane gates pass in the worktree (the worker's report says so, with the exit code).
2. The Manager merges the lane branch into `main` (`--no-ff` for multi-commit lanes is fine;
   a clean fast-forward is fine too).
3. **Main gates run on the merged result.** A packet is *done* only when this passes — lane
   gates prove the packet, main gates prove the composition.
4. The worktree and lane branch are removed.
5. A lane whose merge conflicts is bounced back to its worker with the conflict text. Another
   lane never resolves it; the Manager never resolves it silently.

### Serial resources, allocated up front

Named in the org report as merge hotspots; the packet-writing step allocates them so lanes
never contend:

- **Migrations:** the linear chain is data-engineer's exclusive lane; the Manager pre-allocates
  the next migration number in the packet text.
- **Finding and decision numbers:** the Manager allocates a per-packet range (e.g. "your
  findings are M7-F10–F19") so parallel reports cannot collide. `DECISIONS.md` remains
  Manager-only.
- **`tests/conftest.py` and shared fixtures:** test-engineer custody. Other lanes add
  per-domain fixture modules; they do not edit shared conftest.
- **`pyproject.toml` / `uv.lock`:** workers propose dependencies in reports; the Manager
  applies and re-locks at wave boundaries.
- **`jarvis/api/static/index.html`:** region ownership stated in any two packets that touch it
  (the M6-4a/M6-5a precedent) until a surface milestone justifies splitting the file.

### Waves and scheduling

The Manager opens a milestone by classifying packets into **waves**: wave 0 is the independent
set (one lane each, dispatched together), wave *n+1* depends on wave *n*'s outputs. Rules that
came from M6 evidence: security packets lead their wave; read-only work always overlaps
implementation; schedule at most ~70% of capacity, because findings will spawn packets that do
not exist yet. Warm resumption (`SendMessage` to an existing worker) is preferred over a cold
respawn whenever the same territory continues. A failed worker is resumed with an explicit
"verify your own prior state first" instruction — never replaced cold without a tree-state
check.

M7 runs this workflow at **2 implementation lanes** as the deliberate pilot before M8 scales it.

---

## What must not change here

This document governs implementation *process*. It has no authority over the architecture.
A change to what Jarvis *is* — a layer, a responsibility, an invariant — is an amendment to
the Architecture Specification and belongs to the owner, not to this document, not to the
Manager, and never to a worker.
