# Jarvis Implementation Roadmap

Revision 3 — supersedes the sequence in the Implementation Directive's "Build Order".

Edge-by-edge justification for the sequence below lives in
[`DEPENDENCIES.md`](DEPENDENCIES.md), which is maintained alongside this file. This document says
what order; that one says why, and marks which edges are real dependencies versus §13 ordering.

This is an implementation plan, not architecture. Spec v1.4 §13's *binding* order is unchanged
and unchangeable: universal infrastructure → Affiliate → Finance Tracking → plugin framework →
Trading Analysis → additional types → live trading. What changes below is only how the work is
grouped into milestones inside that order.

---

## Revision 2 change: split "Affiliate Business" into two milestones

**Was:** M4 = Affiliate Business (§13 Step 2).

**Now:** M4 = Business Manager runtime + scheduler. M5 = Affiliate Business.

### 1. Why the dependency order changed

Implementation surfaced a pattern across M2 and M3: components that are correct, tested, and
**dormant** because nothing calls them.

| Component | Milestone | Why it has no caller |
|---|---|---|
| `CredentialManager` | M2 | Nothing executes tools |
| `FairQueue` | M2 | Dispatch is synchronous, so there is no contention |
| `due_for_renotification` / `expire_stale` | M3 | Nothing runs on a timer |

Three components, one cause. Every one of them is driven by something that does not exist yet:
the thing that *wakes up and decides*. Spec §2.1's Business Manager is that thing — it is the
caller for scheduled work, for concurrent capability dispatch, and for the approval lifecycle.

The original plan buried the Business Manager inside the Affiliate Business milestone. But §2.1
makes the Manager a per-business Temporal workflow whose *pattern* is platform infrastructure,
and §4.1 requires that pattern "be treated as the general pattern for any future nesting"
without hardcoding business as a permanently top-level object. A generic, reusable component
specified as generalisable does not belong inside the first concrete instance of the thing it
generalises.

§13 Step 1's own wording supports the split: universal infrastructure is "built against one real
business", which describes interleaving, not a clean handoff.

### 2. Why the new sequence reduces risk

**It stops the dormancy debt from compounding.** Dormant code is unverified code wearing a test
suite. M4 gives all three components real callers, so M5 begins with nothing outstanding.

**It isolates the three riskiest decisions.** D-004 (replay determinism), D-005 (bounded workflow
state), and D-006 (continuation approval model) are three of the eight Critical items from the
architecture review, and none has yet been executed against a real workflow. They all live in the
Business Manager. Building it beside Affiliate-specific logic means a defect in the Manager
pattern presents as a defect in the Affiliate business, and vice versa — two unfamiliar systems
failing together, with no way to bisect.

**It makes the first business type a real test of §4.** §4 requires a new instance of a known
type be addable "via configuration only — no orchestrator code changes". If the Manager is built
during the Affiliate milestone, that requirement is untestable, because the orchestrator and the
business are the same work. Building the Manager first means M5 either is configuration or
visibly is not — which is exactly the signal §4 exists to produce.

**It surfaces the district-readiness constraint while it is still cheap.** §3.2 and §4.1 require
the architecture support inserting District Managers without a Manager redesign. That constraint
is checkable while writing a generic Manager and nearly invisible while writing an Affiliate one.

### 3. Architectural impact

None. No layer added or removed, no responsibility reassigned. The Business Manager keeps exactly
the scope §2.1 gives it — tactical execution, never strategy — and §3.1's Executive
responsibilities remain untouched and unbuilt. The hierarchy in §3.2 is unchanged. This is a
regrouping of implementation work inside §13's binding order.

---

## Revision 3 change: extract the Business Activation Path from the Affiliate milestone

**What changed.** M5 was "Affiliate Business". It is now M5 = Business Activation Path,
M6 = Affiliate Business. Downstream milestones shift by one.

**Why the previous ordering was suboptimal.** An audit for implicit assumptions found that a
business cannot actually be activated. Four gaps, one causal chain:

| Gap | Consequence |
|---|---|
| Nothing calls `Registry.register_instance` | A company cannot be created at all |
| Nothing starts a Manager workflow | An ACTIVE business has no Manager, violating §2.1 |
| Prompt templates default to empty | Every dispatch fails permanently as "missing task definition" |
| `approval.decided` is never published to the bus | **The D-006 continuation loop is open** |

The last is the severe one. A Manager raises an approval and ends its cycle by design; the
operator answers; nothing wakes the Manager. The business stops permanently. The bug survived
review because the audit log already used the event name `approval.decided`, so a search for it
found matches and the loop looked closed.

Folding this work into the Affiliate milestone would have hidden it: the first business would
have been "made to work" by whatever wiring it happened to need, and the wiring would have been
indistinguishable from the business.

**Why the new ordering better reflects the implementation.** Activation is platform work — every
business type needs it, and none of it is Affiliate-specific. Extracting it means M6 is a
configuration exercise, which is the only condition under which §4's "addable via configuration
only — no orchestrator code changes" is testable. This is the same argument as revision 2,
applied consistently: a component every instance needs does not belong inside the first instance.

It also retires two deferred-completion rows rather than opening more — `CredentialManager` gains
a caller through tool execution, and the Manager workflow gets its first live exercise.

**Classification: structural.** Milestone boundaries and sequencing only. No layer added or
removed, no responsibility moved, no invariant weakened. The gaps above are defects against the
existing architecture, not arguments for changing it.

---

## Current roadmap

| # | Milestone | Spec | Status |
|---|---|---|---|
| 1 | Platform Kernel foundation | §0, §0.1, §5, §11, §11.5 | Merged |
| 2 | Execution spine | §2, §2.2, §6, §9, §10 | Merged |
| 3 | Operator surface | §5, §8, §9, §12.5 | Merged |
| 4 | Business Manager runtime + scheduler | §2.1, §2.2, §9 | Merged |
| 5 | **Business Activation Path** | §2.1, §4, §10, D-006 | **Current** |
| 6 | Affiliate Business | §13 Step 2 | Next |
| 7 | Finance Tracking Business | §13 Step 3 | Planned |
| 8 | Plugin framework | §13 Step 4, §4 | Planned |
| 9 | Executive Layer | §3, §3.1 | Planned |
| 10 | Trading Analysis Business | §13 Step 5 | Planned |
| 11 | Additional business types | §13 Step 6 | Planned |
| 12 | Live Trading Business | §13 Step 7, §8 | Planned |

Milestone 9 (Executive Layer) sits after the plugin framework because §13 Step 4 generalises
"once two business types exist for real comparison", and §3.1's cross-business responsibilities —
capital allocation, portfolio balancing — are meaningless with fewer than two businesses to
allocate between. This placement was implicit in §13 and is now explicit.


---

## Milestone report format

Every milestone report carries:

1. Updated roadmap (when changed)
2. **Dependency graph delta** — new or changed edges, each classified Hard, Evidential,
   §13 ordering, or Soft, plus any deferred-completion rows opened or retired
3. Objective
4. Architectural justification
5. Major implementation decisions
6. Defects found and corrected
7. Verification performed
8. Known limitations
9. Merge recommendation

Item 2 exists so the graph is updated as work happens rather than reconstructed later from
memory. A milestone that opens more deferred-completion rows than it retires should say why —
that accumulation is what produced revision 2.


---

## Revision 3: the Developer Shell (operational)

**What changed.** A cross-cutting Shell deliverable lands between M5 and M6: `python -m jarvis`
(or the `jarvis` console script) runs preflight, auto-starts Docker services when absent,
applies migrations, and serves the API, worker, and scheduler in one process with visible
degradation instead of stack traces. From M6 onward, every milestone report carries a new item:
**"Surfaced in the Shell"** — what the milestone's features look like in the running
application, or why they cannot be surfaced yet.

**Why now.** The shell composes; it cannot precede the things it composes. After M5 every
component it needs exists, and the remaining gap was purely operational: four manual startup
steps and no health surface. Earlier was impossible, later buys nothing.

**Classification: operational.** No layer, responsibility, or invariant changes. The
one-process form is a development *topology*; production keeps the worker and API as separate
processes exactly as before. The launcher is registered as the third composition root under the
layering invariant, which requires that decision be made deliberately — this is it, and
`test_composition_roots_hold_no_logic` keeps the root free of behaviour.

**Per-milestone surfacing plan:** M6 — create a Finance company beside the Affiliate one; watch
a Manager wake live. M7 — installed templates page. M8 — Executive view: budget moves between
companies, explained. M9+ — trading analysis appears read-only long before anything can act.

---

## Revision 4: prove the platform with a vertical slice before widening it (structural)

**What changed.** M6 was "Finance Tracking — the second business type." It is now **M6: the
Affiliate vertical slice**, and Finance Tracking moves to M7. The reordering is deliberate and
the reason is the point of this revision.

**Why the previous ordering was suboptimal.** The original sequence added a *second* business
type before the *first* one had ever run end to end. Every layer of the Affiliate slice exists
and is unit-tested in isolation — Manager, capabilities, approval gate, tool execution, audit
trail — but no single company has yet travelled the whole path:

```
create company → Manager wakes → business executes a capability →
action proposed → approval generated → operator approves →
tool executes the approved action → audit + decision trail recorded
```

Adding Finance now would double the type surface while that path is still unproven, which means
a defect in the *platform* would first show up as a defect in *two businesses* and be harder to
localise, not easier. The M5 reconciliation and the M5-F5/F6/F7 chain all taught the same
lesson: things verified in isolation break where they meet, and the meeting points are where
the real bugs live. A vertical slice is nothing but meeting points.

**Why the new ordering is better.** Proving one complete slice validates the platform itself —
the generic Manager, the capability pool, the approval continuation model (D-006), the tool
boundary (D-015), the audit and decision logs. Once that path is green, the *second* business
type (Finance) becomes what D-014 always claimed it was: pure configuration over proven
machinery, and its milestone can be short because it is exercising a path already known to work.
Prove the platform, then widen it — not the reverse.

**Classification: structural.** No architecture changes — no layer, responsibility, or invariant
moves, and the Affiliate slice touches only code that already exists. What changes is the *order*
in which milestones exercise that code, and the acceptance bar: M6's definition of done is now a
working end-to-end transaction, not a new component.

**The first Manager live-run (formerly the M6-2 packet) folds into this slice.** It was always
the hardest and least-tested part of the path; making the whole path the milestone puts that
first live run where it belongs — as the spine of the slice rather than a separate task beside
a new business type.

---

## Current roadmap

| # | Milestone | Spec | Status |
|---|---|---|---|
| 1 | Platform Kernel foundation | §0, §0.1, §5, §11, §11.5 | Merged |
| 2 | Execution spine | §2, §2.2, §6, §9, §10 | Merged |
| 3 | Operator surface | §5, §8, §9, §12.5 | Merged |
| 4 | Business Manager runtime + scheduler | §2.1, §2.2, §9 | Merged |
| 5 | Affiliate Business (definition + provisioning) | §13 Step 2 | Merged |
| — | Developer Shell + desktop application | operational | Merged |
| 6 | Affiliate vertical slice — prove the platform end to end | §2.1, §6, §8, §13 | Merged (report: `docs/reports/M6.md`) |
| 7 | Finance Tracking Business | §13 Step 3 | Merged (report: `docs/reports/M7.md`) |
| 8 | Plugin framework + product identity | §13 Step 4, §4 | Merged (report: `docs/reports/M8.md`) |
| 9 | Executive Layer + governance constitution | §3, §3.1 | Merged (report: `docs/reports/M9.md`) |
| 10 | **Trading Analysis Business** | §13 Step 5 | **Next** |
| 11 | Additional business types | §13 Step 6 | Planned |
| 12 | Live Trading Business | §13 Step 7, §8 | Planned |

The vertical slice is the milestone that proves the platform rather than the infrastructure.
Everything before it built capability; M6 proves the capability composes into a working business.

---

## Product governance (added alongside architectural governance)

A standing priority order now governs how far any milestone reaches:

1. **Platform correctness** — does the right thing, safely.
2. **Complete vertical slices** — whole paths work end to end.
3. **Workflow refinement** — the operator's tasks are smooth.
4. **Product experience refinement** — it becomes genuinely good to use.
5. **Commercial-quality polish** — it becomes premium.

Correctness always comes first. But once correctness exists, **product quality is a first-class
engineering objective, not an optional enhancement** — it has a defined place in the sequence,
and the `product-reviewer` gates any milestone with an operator-facing surface, exactly as the
`architecture-auditor` gates any milestone touching architecture.

The full product constitution — objective, philosophy, inspiration, governance — is
`docs/PRODUCT.md`. In short: Jarvis must eventually feel like premium desktop software; the
current UI is a functional prototype, not the visual direction; the operator should feel they
are operating intelligent companies, not configuring software.

This does not reorder the milestone table. M6 remains the Affiliate vertical slice (correctness
and a complete slice — tiers 1 and 2). Product review begins gating now that surfaces exist, and
its influence grows as the roadmap moves from proving the platform toward refining it.
