# Engineering Report — Sub-Agent Development Organization for Jarvis

Status: recommendation only, nothing implemented. Commissioned after the m6-baseline tag.
Author: Fable (Engineering Manager). Evidence base: the complete M6 execution record —
19 dispatches (15 work packets, 2 reviews, 1 re-review, 1 docs pass) across one continuous
session, plus `docs/DELEGATION.md`, `docs/DEPENDENCIES.md`, and the layering invariant.

The question is not "how many agents can run" but "what actually serialized M6, and which of
those serializers are now removable." Most of this report derives from that record rather than
from first principles, because M6 is the only full milestone this organization has executed.

---

## 1. What actually serialized M6 (the evidence)

M6 ran ~95% serialized: one worker at a time, with only three background-parallel runs (the two
read-only reviewers, and one docs pass alongside a code packet). The causes, ranked by cost:

1. **No git repository.** One shared working tree meant two writers could corrupt each other
   and gates could not run concurrently (`.jarvis-run/` gate records, shared pytest state).
   This forced full serialization of every code packet. *Now removed* — the canonical repo
   exists, which unlocks git worktrees: the single highest-leverage change available.
2. **One live environment.** One Postgres (one `jarvis` database), one Temporal namespace, one
   dashboard port. Live-verification packets (M6-1, -2, -3, and the Postgres-lane tests) would
   have collided. Removable cheaply (per-lane schemas/namespaces).
3. **Discovery-driven packet chains.** Most M6 packets were *created by the previous packet's
   findings* (M6-0 spawned 0b–0h; M6-1 spawned 1b–1d; the audit spawned 4a–4b). A packet that
   does not exist yet cannot be parallelized. This is intrinsic to paying down unexecuted-code
   debt and will shrink — M7+ work on an executed platform should be far more pre-plannable —
   but it never disappears, and it caps the value of static scheduling.
4. **Manager attention.** Decomposition, report reading, decision recording, and security-diff
   reads are Manager-serial by design (DELEGATION.md makes decomposition non-delegable, and M6
   confirmed why: 7 of 15 packets required a Manager arbitration or D-entry mid-stream).
5. **Sequential bookkeeping artifacts.** M6-F finding numbers and D-entry numbers are globally
   sequential; migration files are a linear chain; `DECISIONS.md` is single-writer. Fine at one
   lane; collision-prone at three.

What did *not* serialize M6: file-level conflicts. Packet scoping kept write-sets almost
perfectly disjoint (the one coordination case — two packets touching `index.html` — was solved
with region ownership in the packet text). The existing scoping discipline is the asset that
makes parallelism safe at all; nothing below replaces it.

---

## 2. Natural ownership boundaries

The layering table (DEPENDENCIES.md) already partitions the tree by milestone; territory maps
cleanly onto it. Write-frequency during M6 identifies the hotspots:

| Zone | Packages / paths | M6 write pressure | Natural owner |
|---|---|---|---|
| Kernel & wiring | `kernel/` (config, container, ids, errors, runtime, logging) | Medium — every lane's wiring lands here | platform-engineer (container edits Manager-reviewed) |
| Data | `persistence/`, `migrations/` | Low but **strictly serial** (chain 0001→0006) | data-engineer, exclusive |
| Execution spine | `events/`, `budget/`, `capabilities/`, `security/`, `runtime/` | High — and 6 of 15 packets here were security-boundary work | security-engineer (auth/budget/credential paths), platform-engineer (rest) |
| Registry & contract | `registry/`, `domain/` | Medium; auth paths are security territory | split: security (authorize), platform (bookkeeping) |
| Manager & scheduling | `manager/`, `scheduler/` | High | workflow-engineer |
| LLM | `llm/`, `llm/providers/` | Low post-M6 | platform-engineer (no dedicated agent warranted yet) |
| Operator surface | `api/`, `api/static/`, `kpi/`, `notifications/`, `approvals/` (rendering) | High; `index.html` is a single-file merge hotspot | operator-surface-engineer; approvals *logic* stays security |
| Business types | `businesses/` | Low until M8, then the main growth area | business-type-author(s) — data-only, embarrassingly parallel post-M8 |
| Shell | `shell/` | Low | platform-engineer |
| Test infrastructure | `tests/conftest.py`, `scripts/gates.sh`, fixtures | Shared hotspot — 5 packets touched conftest | test-engineer owns; others add test *files*, never shared fixtures |
| Governance docs | `docs/DECISIONS.md`, `DEPENDENCIES.md`, `ROADMAP.md`, packets, reports | Manager-only (one worker violation in M6, harmless but noted) | Fable exclusively |
| Dependency manifests | `pyproject.toml`, `uv.lock` | Rare | Fable batches; workers propose in reports |

---

## 3. The sub-agent hierarchy

The existing 13-agent roster survives contact with reality; M6 used 8 of them and the design of
the unused ones remains sound. Refinements below are ownership sharpening, not restructuring.

**Communication topology: hub-and-spoke through Fable, no peer-to-peer.** This is deliberate.
Peer communication would trade the Manager bottleneck for an untraceable-decision problem; the
context-integrity model (reports in, packets out) is what kept a 19-dispatch milestone coherent.

| Agent | Mission | Owns (writes) | Never touches | Inputs | Outputs | Talks to | Independent work |
|---|---|---|---|---|---|---|---|
| **Fable (EM)** | Architecture, decomposition, decisions, merges, memory | `docs/` governance, merge queue, packet files | implementation (except trivial) | owner directives, reports, verdicts | packets, D-entries, milestone reports, merges | everyone | — |
| **delivery-coordinator** | Execute prepared multi-packet chains; gate-retry loops | nothing (no edit tools) | everything | ≥2 prepared packets | consolidated reports, verbatim escalations | Fable, assigned workers | dispatching any pre-written independent packet set |
| **platform-engineer** | Backend services default lane | kernel (non-container), registry bookkeeping, kpi, notifications, llm, shell, api routes (non-approval) | security paths, migrations, workflow code, governance docs | packet | bounded report | Fable/coordinator | yes — any gate-covered packet in its zone |
| **security-engineer** | Every path where a mistake authorizes the wrong thing | approvals logic, security/, credentials, budget enforcement, registry auth, tools, identity | operator copy, migrations, governance docs | packet + quoted D-entries | report + boundary statement | Fable only (never via coordinator when likely to escalate) | rarely — its packets usually gate others |
| **workflow-engineer** | Temporal workflows, determinism, concurrency | manager/, runtime/, scheduler/ | security paths, persistence models, governance docs | packet + replay rules | report + live-vs-simulated | Fable/coordinator | yes, within its zone |
| **data-engineer** | Schema, migrations, session scoping | persistence/, migrations/ | business logic, governance docs | packet + allocated migration slot | report + migration verification | Fable | **no** — the migration chain is serial by nature |
| **operator-surface-engineer** | §12.5 compliance, dashboard, operator copy | api/static/, rendering boundaries, operator-facing copy | approval semantics, security paths | packet + D-007 table | report + painted-against-real-data evidence | Fable/coordinator | yes |
| **business-type-author** | Type definitions, pure data (D-014) | businesses/ | generic machinery (that's the point) | packet + type spec | report; D-014 gate green | Fable/coordinator | **yes — N in parallel post-M8**, one per type |
| **test-engineer** | Executable guarantees; shared fixture custody | tests/ shared infra, conftest, gates.sh, fixtures | jarvis/ (findings, not fixes) | packet | report + coverage delta | Fable/coordinator | yes |
| **docs-writer** | Truthful docs | all docs except governance set | DECISIONS/DEPENDENCIES/ROADMAP (Manager's memory) | packet + facts to verify | report citing verification | Fable/coordinator | yes — fully parallel (no gate contention) |
| **refactorer** | Behaviour-preserving cleanups | whatever the packet grants | assertions, behaviour | packet | report | Fable/coordinator | **only with an exclusive tree lock** — cross-cutting by nature |
| **architecture-auditor** | MERGE/REVISE/ESCALATE verdicts | nothing (read-only) | — | diff/tree + decisions | verdict + ranked findings | Fable only | yes — always parallel-safe |
| **product-reviewer** | SHIP/REVISE verdicts on the real running surface | nothing (read-only; may run processes) | — | running system + PRODUCT.md | verdict + ranked findings | Fable only | yes — always parallel-safe |
| **spec-archaeologist** | "What did we decide about X" in 200 words | nothing (read-only) | — | question | answer with citations | anyone's packet prep | yes |

---

## 4. Maximum effective team size

"Team size" here means *concurrently active* agents, not roster size.

| Era | Concurrent lanes | Composition | Why not more |
|---|---|---|---|
| **Today (M7)** | **4** | 2 implementation worktrees + 1 read-only (reviewer or archaeologist) + 1 docs/coordinator | M7 is deliberately short and exercises proven paths; its packets are mostly a dependent chain. More lanes would idle. |
| **After M7 (M8, plugin framework)** | **5–6** | 3 implementation worktrees + 1–2 type-authors + reviewers overlapped | M8 generalizes machinery (serial-ish) while type work parallelizes; first era where 3 code lanes stay busy. |
| **After M10** | **6–8** | 2 platform lanes (shrinking, per D-019/§14) + 2–3 type-authors + per-business ops/audit lanes + reviewers | Platform stabilizes; growth is data-only types and operational review — the embarrassingly parallel kind. |
| **Diminishing returns** | **~5 concurrent code-writing lanes, at any era** | — | See below. |

The ceiling is not compute; it is three serial resources:

1. **Fable's attention.** Every packet costs a fixed Manager overhead (decompose ≈ write the
   packet, read the report, record decisions; security packets add a mandatory diff read).
   In M6 that overhead was comparable to worker runtime for small packets. Beyond ~5 active
   lanes the Manager becomes a queue and lane latency rises to Manager latency — you get more
   in-flight work, not more merged work.
2. **The merge gate.** Merges land one at a time (gates on merged result). Merge throughput
   ≈ one packet per gate-suite runtime; with today's 594-test suite (~2–3 min) this is far from
   binding, but it grows with the suite and is strictly serial.
3. **Discovery.** Findings-driven packets (the M6 norm) cannot be scheduled before they exist.

Coordination overhead by scale (qualitative, from M6's observed costs): at 2 lanes, overhead is
one extra merge-order decision per wave; at 4, add finding-number allocation, fixture-custody
routing, and occasional region-ownership clauses in packets; at 6+, add a real merge queue with
rebase churn on `kernel/container.py` and `tests/conftest.py`, and the coordinator becomes
mandatory rather than optional. Past ~5 code lanes, each additional lane costs more Manager
serial time than it adds parallel work.

---

## 5. Bottlenecks, and what removing each buys

| # | Bottleneck | Why it exists | How it limits | Fix | Expected gain |
|---|---|---|---|---|---|
| B1 | Single working tree (historical) | No git until yesterday | Forced ~95% serialization of M6 | **Git worktree per implementation lane**; lane gates run in-worktree; Fable merges | 1 → 3 concurrent code lanes; the dominant unlock |
| B2 | One live environment | Single compose stack, one DB name, one Temporal namespace, fixed ports | Live-verification packets and Postgres-lane tests collide across lanes | Parameterize by lane: `JARVIS_DATABASE_URL` per-lane database, Temporal namespace per lane, port offsets; one small test-infra packet (fold into D-025.2's Postgres-lane work) | Unblocks concurrent live verification; removes the flakiest class of cross-lane failure before it appears |
| B3 | `.jarvis-run/` + manifest shared state | Gate records are cwd-relative | Concurrent gate runs interleave records | Automatic once B1 lands (each worktree has its own) | Included in B1 |
| B4 | Manager attention | Decomposition/decisions non-delegable (by design, correctly) | Hard ceiling ~5 lanes | Don't remove; *spend better*: coordinator for mechanical chains, batched decision recording at wave ends, 300-word report caps enforced, spec-archaeologist for recall | +1 effective lane |
| B5 | Migration chain | Linear numbered files | Two lanes cannot both add a migration | Fable pre-allocates migration slots at packet-writing time; data-engineer is the only migration author | Conflict rate → ~0 at no cost |
| B6 | `tests/conftest.py` | Shared fixtures accrete | 5 M6 packets touched it; classic merge hotspot | test-engineer custody; other lanes add per-domain fixture modules, never edit shared conftest | Removes the likeliest merge conflict |
| B7 | `index.html` monolith | Entire dashboard is one file | Any two surface packets collide | Region-ownership clauses now (worked in M6); split into modules at the next surface milestone, not before (§14 — no speculative restructure) | Adequate now; revisit with evidence |
| B8 | Sequential finding/D numbers | Single global sequences | Parallel reports would collide on M6-F-style numbers | Fable allocates number ranges per packet (e.g., "your findings are M7-F10–F19"); DECISIONS.md stays single-writer | Trivial fix, prevents renumbering pain |
| B9 | Security review depth | Opus + mandatory Manager diff-read on every boundary | Security lane is slow and often gates others (6 of 15 M6 packets) | Keep the depth (non-negotiable). Mitigate by scheduling: security packets first in each wave so their outputs stabilize while other lanes run; reviews overlap the next wave | Latency hiding, not reduction — correct trade |
| B10 | `pyproject.toml`/`uv.lock` | One dependency manifest | Two lanes adding deps conflict | Workers propose deps in reports; Fable applies and re-locks at wave boundaries | Conflict rate → 0 |

---

## 6. Should the repository be restructured before M7?

**No structural changes.** Three arguments, all evidential:

1. M6's serialization was environmental (B1–B3), not structural — file conflicts essentially
   never happened under packet scoping. Restructuring would treat the disease we don't have.
2. §14 and D-019 set a binding bias against speculative architecture. A pre-M7 package
   reorganization to serve hypothetical parallelism is precisely what they prohibit.
3. M8 (plugin framework) will *force* a real seam between generic machinery and type content,
   with two concrete types as evidence. Any partition drawn today would be redrawn then.

**Three operational changes before M7** (none touches source structure):

- **Adopt worktree-per-lane** (B1) — pure process; zero repo changes.
- **Parameterized live-test lane** (B2) — one small test-infra packet, bundled with the already-
  decided D-025.2 Postgres test lane. The only code change, and it is test infrastructure.
- **Merge-queue protocol** (§7 below) — process, written into DELEGATION.md by amendment.

M7 itself should run at **2 lanes** as the pilot: it is deliberately small (a read-only business
type exercising proven paths), which makes it the cheapest possible rehearsal of the worktree
workflow before M8 raises the stakes.

---

## 7. Fable's orchestration strategy — what changes

**Decomposition → dependency graph, explicitly.** Each milestone opens with packets classified
into waves: wave 0 = independent (dispatch all, one worktree each), wave 1 = dependent on wave 0
outputs, etc. M6 did this implicitly and serially; making it explicit is what lets the
coordinator run a wave unattended.

**Scheduling rules** (from M6 evidence):
- Security packets lead their wave (they gate others; their findings spawn the most follow-ups).
- Read-only work (reviews, research, docs verification) *always* overlaps implementation — it
  was the only parallelism M6 exploited, and it was free.
- Discovery buffers: schedule at most ~70% of a wave's capacity; M6 says the remaining 30% will
  be consumed by packets that don't exist yet.

**Verification gates, doubled.** Lane gates (in-worktree, pre-merge) prove the packet; main
gates (post-merge) prove the composition. A packet is "done" only after main gates pass. The
`SubagentStop` hook already wired in `.claude/settings.json` enforces the lane half.

**Merge sequencing.** Fable merges, one lane at a time, in dependency order (data → security →
platform/workflow → surface → docs). A lane whose merge conflicts is bounced back with the
conflict, never resolved by another lane. Riskiest merges land earliest so audits see final
state.

**Context management** (the actual scarce resource):
- Reports capped at 300/500 words, enforced by re-request rather than tolerated overrun.
- Warm resumption over cold respawn: `SendMessage` to an existing agent preserved full context
  twice in M6 (a mid-packet server failure, and a follow-up packet to the same specialist) at
  a fraction of a cold start's cost. Default to it whenever the same territory continues.
- Handoff via repo, not conversation: packets quote decisions inline; workers never need the
  Manager's transcript. This already works — keep it absolute.
- Fable reads code only per the review-depth table (Tier C and security always; otherwise
  reports and verdicts only).

**Recovery protocol** (learned from the 529 incidents): a failed worker is resumed from
transcript with an explicit "verify your own prior state first" instruction; if the tree shows
no edits, re-execute from the plan; never dispatch a cold replacement without a tree-state
check. Packets are written idempotently ("inspect, don't assume") so a re-run is safe.

**Failure containment:** a worktree that produced garbage is discarded (`git worktree remove`),
costing nothing to `main` — this replaces M6's only-defense of sequential caution.

---

## 8. Recommended permanent organization

```
Owner — spec, amendments, approvals, capital
  │
  Fable — Engineering Manager
  │   decomposition · decisions (DECISIONS.md) · merge queue · milestone reports · memory
  │
  ├── delivery-coordinator ──── runs prepared waves; forwards escalations verbatim
  │     ├── Lane 1  platform-engineer      (worktree)
  │     ├── Lane 2  workflow-engineer      (worktree)
  │     ├── Lane 3  operator-surface-eng.  (worktree)
  │     └── Lane N  business-type-author×N (worktrees; post-M8)
  ├── security-engineer ─────── own lane, Fable-direct, leads each wave
  ├── data-engineer ─────────── exclusive serial migration lane
  ├── test-engineer ─────────── gates & shared-fixture custody
  ├── refactorer ────────────── exclusive tree lock when active
  ├── docs-writer ───────────── always-parallel
  └── read-only (always parallel, Fable-direct):
        architecture-auditor · product-reviewer · spec-archaeologist
```

**Coordination protocol:** packet (repo file) → dispatch (worktree) → lane gates → bounded
report → Fable merge (queue, dependency order) → main gates → decisions distilled → next wave.
Escalations bypass everything and reach Fable verbatim. No agent writes another's territory; no
agent writes governance docs; nobody but Fable merges.

**Verification pipeline:** lane gates → main gates → auditor (Tier B/C and all security) →
product review (any operator-visible surface) → milestone tag. Both reviewers run concurrently
with the next wave's implementation.

**Sustainable throughput estimate.** M6 measured ~2 merged packets/hour fully serialized with
discovery-heavy work. With 3 lanes, overlapped reviews, and the merge queue: a sustained
**1.8–2.5×** improvement is realistic (not 3× — discovery chains and Manager serial costs
don't parallelize). Post-M8, type-authoring waves are near-linear in lane count up to the
~5-lane Manager ceiling. The honest summary: parallelism buys roughly a doubling now and more
later, and every gain past that must come from making packets smaller-than-discovered rather
than from more agents.

---

## Actions requested of the owner (none taken)

1. Approve the three pre-M7 operational changes (worktrees, parameterized live-test lane,
   merge-queue protocol as a DELEGATION.md amendment).
2. Decide whether this report, if accepted, is committed to `docs/reports/` (it is currently
   an untracked file).
3. M7 then proceeds as the 2-lane pilot of this organization.
