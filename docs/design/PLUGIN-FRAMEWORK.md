# The Plugin Framework

**Status:** design, awaiting Manager review. No implementation. Packet M8-1, Lane A, wave 0.
**Scope:** the four framework questions M6 and M7 accumulated — installer generalization
(M7-F1), contract-refresh-on-upgrade (audit F-A / M7-F62 / M7-F24), type packaging (§4), and
what M7's evidence proves about which parts of the platform a type may vary.

This document decides nothing that D-001…D-028 already decided, and proposes nothing that
lacks a finding behind it. Where a resolution would change a MUST/MUST NOT, alter a D-entry's
semantics, or touch graduation state, it stops and says so (Part 7).

Every claim about live behaviour below was read out of the live database read-only on
2026-07-27. Nothing was written.

---

## Part 0 — What M7 proved

M7 installed a second business type against a platform built around the first. The M7-4
architecture verdict recorded the honest result: **three generic changes landed, all
data-shaped, all demonstrated need** — against a plan that had predicted zero. That is the
evidence base for everything below, and it is worth stating precisely what each change was,
because the shape of the three is the finding.

| # | Change | Shape |
|---|---|---|
| 1 | `kpi_mappings` on the definition, `KpiSource` enum, `CycleContext.measures_kpis` (D-027) | a new **data field** on the type + a platform-owned **enumeration** of facts |
| 2 | `KpiDirection` on `KpiTarget` (M7-F30 → M7-F55) | a new **data field**, additive with a default |
| 3 | `compliance_requirements` injected verbatim into the planning prompt (D-027.5) | a **read** of an existing stored field |

Not one of them was a branch on the type's name. Not one added a Manager subclass, a
per-type code path, or a hook. D-014's "a business type is data" survived a second type
intact, and the platform's response to a new type's needs was, three times out of three, *a
new data field whose meaning the platform owns*.

Two composition-root edits accompanied them, recorded in the M7 report: `BUILTIN_TYPES`
(M7-F1) and `domain/kpi.py`'s placement so M4 and M5 could share the mapping vocabulary
without a forward import. Neither was a change to how a type behaves; both are the kind of
edit `docs/DEPENDENCIES.md` exempts a composition root for.

**The conclusion that governs this document:** the extension mechanism the platform actually
has is *type-declared data interpreted by platform-owned vocabulary*. The framework's job is
not to invent a plugin system. It is to name that mechanism, enumerate its surface, and fix
the three places where it leaks.

### The asymmetry M7 left behind

M7 also left a discovered fault line that no finding named as one, and it is the key to
Part 4. **Some type data is already read live from the Registry on every use; the rest was
snapshotted into the contract at creation and has never been read again.**

Read live, today, from `business_types.plugin_metadata.definition`:

| Field | Reader | Consequence of a version bump |
|---|---|---|
| `prompt_templates` | `KernelActivities.dispatch_capability` | every existing company uses the new prompts on its next dispatch |
| `kpi_mappings` | `ManagerActivities.load_cycle_context` → `measures_kpis` | measurement starts or stops for existing companies |
| `tool_registry` | the effect binding on the approved-action path (D-024) | a tool's implementation key changes under existing companies |
| `display_name`, `description` | `_type_catalog` in `jarvis/api/app.py` | the kind and blurb on every company card change |

Snapshotted at `create_company` and never refreshed:
`kpi_targets`, `wake_conditions`, `capability_permissions`, `autonomy_policies`,
`compliance_requirements`, `budget`.

So the platform is **already a hybrid** of contract-as-snapshot and contract-as-view. The
open question was never "which model do we adopt" — both are in production. It is "where is
the line, and is it in the right place". Part 4 answers that.

---

## Part 1 — Type-parameter surface vs frozen platform

This is the framework's actual contract with a business type, and the answer to question 4.

### A type MAY vary these, as data

| Surface | Field | Bound by |
|---|---|---|
| Which work it can do | `capability_permissions[].capability` | `CapabilityType` membership (platform) |
| What tools and credentials each capability may reach | `tool_scope`, `credential_refs` | must be a subset at the pool boundary (D-002) |
| Per-invocation ceiling | `max_invocation_budget_usd` | D-003's innermost scope |
| What it can propose | `autonomy_policies[].action_type` | A-003's dotted pattern; `graduation_eligible` false is mandatory for capital (§8) |
| How it is instructed | `prompt_templates` keyed `{type}.{capability}` | one template per permitted capability, enforced at install |
| What it must obey | `compliance_requirements` | owner-signed text, injected verbatim (D-027.5) |
| What it aims at | `default_kpi_targets` (key, label, target, unit, direction) | §3.1 sets targets; the Manager may not change them |
| How each aim is measured | `kpi_mappings` (key → `KpiSource`) | `KpiSource` membership (platform) |
| When it wakes | `schedule_cron`, `event_triggers` | `event_triggers` ⊆ published event types |
| Which tools exist for it | `tool_registry` (name → implementation key) | the implementation is platform code |
| How it is offered | `display_name`, `description`, suggested budget and ceiling | §12.5 vocabulary |

### A type MUST NOT vary these — the frozen platform

- **The Business Manager workflow.** One generic workflow (§2.1). A type supplies the
  configuration it runs under. Changing it is not a type change.
- **The cycle shape.** plan → dispatch → synthesize → measure → record. D-021 owns where a
  cycle begins; D-023 owns dependent sequencing; D-027 owns where measurement sits.
- **`CapabilityType` membership.** §2.2's capabilities are pool-wide and generic, never
  per-business specialists. Adding one is a platform change with a §2.2 argument behind it.
- **`KpiSource` membership.** D-027 ratified that a source is an enum, not an expression:
  the platform owns the arithmetic so a type can never author a number.
- **Attainment, health, and banding.** D-009 puts the Health Score in the platform, not in
  each business. A type declares direction; it does not declare a formula.
- **The approval gate and its rendering.** D-011, D-013, D-015, D-024 and §8's hard
  constraints. A type names action types; it never decides whether one needs approval, and
  it never writes approval text.
- **Identity derivation (D-002), the budget hierarchy (D-003), the lifecycle state machine
  (D-008), the audit and decision logs (§11).**
- **Tool implementations.** A type names an implementation key. The implementation lives on
  the D-015 path, in platform code, where credentials materialise.
- **Operator vocabulary (§12.5).** A type's operator-facing strings are checked against the
  same forbidden list as the dashboard.

**The rule that generalises it:** a type may declare *what it wants*; the platform decides
*what that means and whether it is allowed*. Every M7 change obeyed this. Every future one
must, and a proposed type field that would require the platform to execute type-authored
logic is the signal that D-014 is being reopened — an escalation, not a packet.

---

## Part 2 — Installer generalization (M7-F1)

### What exists

`BUILTIN_TYPES: tuple[BusinessTypeDefinition, ...] = (AFFILIATE, FINANCE)` lives in
`jarvis/kernel/container.py` and is iterated by `ensure_builtin_types` with a per-type
version gate: install when the installed version differs, skip when it matches. The gate
lives in the caller because `install_business_type` deliberately refuses a duplicate version
(M6-F22, M7-F4) — a design that has now held correctly three times (M7-F36, M7-F57).

### What is wrong with it

1. **The list is in a composition root.** M8's own success criterion is a third type
   installable "with zero composition-root edits". Today adding one edits `container.py`.
2. **The containment does not contain the documented failure.** `ensure_builtin_types`
   catches `RegistryError`, with a comment stating that one built-in failing must not take
   the others with it. But `ProvisioningService.install` raises **`ConfigurationError`** for
   the one defect it is documented to detect (a permitted capability with no prompt
   template), and `ConfigurationError` is a sibling of `RegistryError` under `JarvisError`,
   not a subclass. A built-in with a missing template therefore aborts the whole loop:
   every type after it in the tuple never installs, and `/api/company-templates/install-builtin`
   — the first-run recovery route whose whole purpose is that an empty-template state is
   never a dead end — returns a 500. With two types this is a coin flip. With three it is a
   liability. (**M8-F1**)
3. **A skip is silent.** The `RegistryError` branch logs a warning and continues. Nothing
   audits it, and nothing surfaces it. M7-F1's failure was a type that existed, passed its
   tests, and never reached a live registry; a silently skipped install is the same failure
   with a log line. (**M8-F2**)
4. **Same-version definition drift is undetected.** M6-F22 recorded it and it is still open.
   The live database proves it concretely: `affiliate` v1.0.1's stored definition JSON has
   **no `kpi_mappings` key at all** — the blob was serialized before D-027 added the field,
   the version never changed, so the installed row still carries a pre-D-027 schema. It is
   harmless today (the field defaults to `()` on validate) and it is the general case of the
   bug that has now required three deliberate version bumps to work around. (**M8-F3**)

### The design

**Nothing here is a plugin system.** The demonstrated need is three types.

**2.1 — Move the catalog out of the composition root.** `BUILTIN_TYPES` moves to
`jarvis/businesses/catalog.py`, next to the types it lists. `container.py` imports one
symbol. Adding a type is then a one-line edit in the `businesses` package and zero edits in
a composition root, which is the M8 success criterion satisfied by a file move rather than a
mechanism.

**2.2 — Make the catalog an injected sequence, not a module global.** `PlatformKernel`
accepts `builtin_types: Sequence[BusinessTypeDefinition] | None = None`, defaulting to the
catalog, in the same shape it already accepts `templates`, `provider`, and `secrets` for
tests. `ensure_builtin_types` iterates whatever it was given. **This parameter is the entire
extension path.** §4's wizard-installable future, an operator-uploaded type, or an M11
package loader all supply a different sequence; none of them touches
`ensure_builtin_types`, the version gate, or `install()`. No discovery, no scanning, no
registry-of-registries, no ordering rules — because none of those has a demonstrated need,
and D-014 already rejected import-side-effect registration on the grounds that it failed on
restart and was invisible to the audit log (M5-F3).

**2.3 — Per-type containment that actually contains.** Catch `JarvisError`, not
`RegistryError`, so a validation failure isolates to its own type. Every skip writes an
audit record (`business_type.install_skipped`, actor `platform`, carrying the type name and
the failure class — never the exception text, which is engineer-facing) and the templates
surface reports the count of types that could not be installed. Closes M8-F1 and M8-F2.

**2.4 — Generalize install-time validation.** `install()` already refuses a type whose
permitted capability lacks a template. Three more checks, each with a recorded finding
behind it and each a pure function of the definition — no new layer, no new dependency:

| Check | Finding |
|---|---|
| every `kpi_mappings.key` matches a `default_kpi_targets.key` | D-027.2's keys are what let attainment pair an observation with its goal; a mismatch writes observations nothing reads |
| `event_triggers` may not contain `capability.result_returned` | M6-F10: under D-001 every result is awaited inside the cycle that asked for it, so subscribing is a self-sustaining wake loop bounded only by `max_cycles_per_day` |
| a type declaring `kpi_mappings` may not subscribe to `KPI_THRESHOLD_BREACHED` | M7-F35, which named install-time validation as the candidate guard for exactly this |

**2.5 — A staleness detector, not a staleness fixer.** Store a digest of the definition JSON
alongside the installed row. At startup, when the version matches but the digest differs,
**log and audit a warning; do not install**. Auto-installing at an unchanged version would
destroy the M6-F22/M7-F4 gate semantics and the `DuplicateBusinessError` contract that three
milestones have relied on. This turns "a developer must remember to bump the version" from a
convention into a detected omission. Closes M8-F3. (Deliberately a detector: the fix is
still a version bump, made by a person.)

---

## Part 3 — Type packaging (§4)

### The question, restated honestly

"What is a business type as an artifact, such that M10's Trading Analysis installs through
configuration only?"

### The answer

**It already does, and the artifact does not need to change.** The artifact is:

- **at authoring time:** one module-level frozen `BusinessTypeDefinition` value, containing
  zero functions and zero classes (asserted against the AST by
  `tests/test_affiliate_type.py` and `tests/test_finance_type.py`);
- **at rest:** its JSON in `business_types.plugin_metadata.definition`, which is what every
  runtime reader actually consumes;
- **at instantiation:** `ProvisioningService.create_company(definition, display_name, budget,
  ceiling)` — a signature that *is* §4's "configuration only" requirement, per D-014.

Reconciled with D-014's data-only gate: nothing here adds executable surface to a type.

### What Trading Analysis will actually need — and it is not packaging

Walking §13 Step 5 against Part 1's table, a genuinely complex type consumes the frozen
platform's extension points, not a richer artifact format:

1. **New `KpiSource` members.** Trading Analysis will want metrics the three existing
   sources cannot express. Adding a source is a platform change (the platform owns the
   arithmetic, D-027) and it is *the* predictable M10 dependency. **M8-F4.**
2. **Tool implementations on the D-015 path**, if it ever performs an effect. Named by
   `tool_registry`, implemented in platform code.
3. **Nothing else.** Its capabilities are drawn from §2.2's existing seven. Its autonomy
   policies are `AutonomyPolicy` values — and §8's hard constraint (no graduation for trade
   execution in v1) is enforced by two independent guards already in place.

Building a manifest format now would not remove either dependency. It would be speculative
generality (§14) that leaves the real M10 blocker untouched.

### The one strain worth naming, and the trigger that would justify acting on it

A type's *prose* — prompt templates and owner-signed compliance requirements — is authored
as Python string literals. Finance carries seven owner-approved compliance lines, quoted
verbatim into a `.py` file with a comment explaining their provenance, and M7-F50/F-C traced
a live operator-surface defect to the content of those exact lines. Prose embedded in code
is prose that is diffed as code and reviewed as code.

The non-breaking future form, specified but **not built**:

```
jarvis/businesses/types/<name>/manifest.py     # the definition value, prose-free
jarvis/businesses/types/<name>/prompts/*.md
jarvis/businesses/types/<name>/compliance.md
```

with a **framework-side** loader (never inside a type module — a reader function there would
break the AST gate) that inlines the prose and produces the same `BusinessTypeDefinition`
value. The registry blob, and therefore every runtime reader, is unchanged. This is
compatible with Part 2.2 by construction: the catalog's contract is "produce a
`BusinessTypeDefinition`", and it does not care whether the value was a literal or was read
off disk.

**The trigger:** the first type whose compliance text requires owner sign-off on a document
the owner cannot review inside a Python literal, or the first time compliance text must be
versioned independently of the code that carries it. Not before. **M8-F5** records this so
M10 decides with evidence rather than rediscovering the question.

---

## Part 4 — Contract refresh on upgrade

The hard one. Audit finding F-A is its statement of the problem: `KpiDirection` applies only
to companies created after `finance_tracking` 1.0.2, because contracts snapshot
`default_kpi_targets` at creation and no refresh path exists (M7-F24). Portfolio Watch's
stored targets carry no direction, so its freshness metric still scores backwards.

### 4.1 — Snapshot or view? Both, and the line is *authority*

Part 0 established that the platform already reads four type fields live and snapshots six.
The question is not which model to adopt but where the line belongs. The principle:

> **The contract is a snapshot of what the operator agreed to, and a view of how the type is
> currently implemented. A field is a snapshot when the operator or a platform safety
> property owns its value. A field is a view when the type owns it and the operator never
> chose it. A field that the type owns but the operator was *shown as a promise* is a
> snapshot that refreshes with consent — and the consent is precisely what turns the current
> view into the next snapshot.**

There is precedent for a contract field being deliberately non-authoritative:
`BusinessContract.lifecycle_state` is written once and never read for authorization —
`authorize_invocation` reads state live from the instance row, because "a dispatch check
that cannot see the current state is not a check". Contract-as-partial-view is established
practice with a recorded rationale, not a new idea.

### 4.2 — The three bands

**Band A — Live. Already a view; a version bump propagates immediately; no consent, no
migration.**
`prompt_templates`, `kpi_mappings`, `tool_registry`, type `display_name` and `description`.

This is today's behaviour, recorded rather than changed. It is safe because none of these
fields is an authorization, an amount, or an operator promise: prompts shape instruction,
mappings decide whether a number is observed, the tool registry names an implementation
whose *permission* still lives in the contract's `tool_scope`.

**Band B — Refreshed on upgrade, with operator consent.** Type-owned values that the
operator was shown and that carry no authorization.

| Field | Why it refreshes | Live evidence |
|---|---|---|
| `kpi_targets` — `direction`, `operator_label`, `unit` | descriptions of what a metric *is*, not how ambitious the goal is | Portfolio Watch (F-A, M7-F62) |
| `kpi_targets` — membership (add keys the type declares, drop keys it dropped) | a target with no mapping is unmeasurable; a mapping with no target writes nothing readable | — |
| `kpi_targets.target_value` | today the type default is the *only* source (M7-F24 confirmed no per-instance override path exists), so refreshing is lossless **by construction** | all three companies |
| `wake_conditions.schedule_cron`, `wake_conditions.event_triggers` | type-owned; a stale trigger is a live defect | Trailhead (M6-F10) |
| `compliance_requirements` | owner-approved text; a stale contract runs a company under superseded rules **and feeds them to the planner verbatim** (D-027.5) | — |

Two constraints on Band B, both load-bearing:

- `wake_conditions.max_cycles_per_day` is **not** in Band B. It has no field on
  `BusinessTypeDefinition` — it is a contract default (48). The type does not own it, so a
  type upgrade may not move it.
- `target_value`'s lossless-by-construction argument **expires the day a per-instance target
  edit surface lands.** That surface is anticipated (M7-F3 → M7-F24, and the M8 UI Phase 3
  workspaces). When it lands, refresh needs per-field provenance ("did the operator choose
  this value?") and the whole-target rule must narrow to the descriptive fields. Recorded as
  **M8-F6** so it is a scheduled consequence rather than a future regression.

**Band C — Never refreshed.** Instance-owned, or a security surface.

| Field | Why never |
|---|---|
| `business_id`, `business_type`, `display_name`, `created_at` | identity; §0.1 makes identifiers permanent |
| `budget.business_cap_usd`, `budget.wake_cycle_ceiling_usd` | the operator's money. The live data is the argument: Trailhead $25.00/$1.00, Summit $25.00/$2.00, Portfolio Watch $15.00/$2.00 — Summit's ceiling was an explicit operator choice (M6-F23/M6-F25) and Portfolio Watch's cap differs from its type's suggestion. A type upgrade that moved a spending limit would be the platform overriding a person about money. |
| `lifecycle_state` | never authoritative; the instance row is |
| `capability_permissions`, `autonomy_policies` | **the authorization records.** `authorize_invocation` reads tool scope, credential refs, and capability permission off the contract; `declared_action_types` and `requires_approval` are derived from `autonomy_policies`. Refreshing them from a type would let a version bump widen an existing company's reach with no human in the loop. Frozen in v1 — see Part 7. |
| graduation counters | not a contract field at all. See 4.5. |

### 4.3 — Consent: not the §8 approval queue

A refresh needs the operator's agreement. It must **not** be an `ApprovalRequest`.

`ApprovalRequest` carries an `action_type`, and three mechanisms key on that string: the
graduation counters (D-010, A-003), the effect binding (D-024), and approval rendering
(D-011). Routing a configuration change through §8's queue would give it a graduation
counter — meaning that after five clean acceptances, **company updates would begin applying
unattended**. That is precisely backwards, and it is a good argument that §8 governs *actions
a company proposes*, not *changes the platform makes to a company*. A type upgrade is not
proposed by a business; the platform made it and the operator accepts it.

The design: a distinct, non-graduating **pending company update**, held against the business
instance, surfaced on the company's own page, resolved by an explicit operator action.
Audited on creation and on resolution, with a Decision Log entry (D-008 I-6's shape). It
never enters the approvals queue, never has an `action_type`, and can never graduate — the
absence of an `action_type` is what makes that structurally true rather than a promise.

Until it is accepted, **the company keeps its snapshot** — which is exactly today's
behaviour. The un-consented state is the status quo, so nothing regresses if an operator
ignores it, and a company can never be silently reconfigured by a developer's version bump.

Declining is a real outcome, recorded, not a deferral loop. A declined refresh is re-offered
only on the next version change.

### 4.4 — Where refresh runs, and how a running Manager learns

Refresh is a Registry write. Not a workflow, not an activity of the Manager: D-004 keeps
nondeterminism in activities, and this is neither a cycle step nor a model call.

- `plan_refresh(business_id) -> ContractRefreshPlan` — pure, no writes. Diffs the stored
  contract against the installed definition row. **Both sides are stored values**, so the
  rendered plan is D-011-shaped by construction: no model sits between the change and the
  human.
- `apply_refresh(business_id, plan)` — writes the new contract, audits
  `business.contract_refreshed` with the before/after, writes the Decision Log entry, and
  re-validates the result through `BusinessContract` (a refresh that would produce an
  invalid contract — for instance a type that dropped every wake condition — is refused, not
  written).

**Propagation, verified against the readers:**

| Band B field | Reader | Takes effect |
|---|---|---|
| `wake_conditions.event_triggers` | `Scheduler` sweep, reading the contract per sweep | next sweep, no restart |
| `wake_conditions.schedule_cron`, `max_cycles_per_day` | `load_cycle_context` activity, per cycle | next cycle, no restart |
| `kpi_targets` (attainment, health, goals drill-down) | `KpiEngine` and the API, reading the contract per request | immediately |
| `kpi_targets` **in the planning prompt** | `ManagerState.kpi_targets`, seeded once at Manager start by `ManagerLifecycle.reconcile` and carried in workflow state | **not until continue-as-new or a Manager restart** |
| `compliance_requirements` in the planning prompt | `plan_cycle`, reading the contract per cycle | next cycle |

That fourth row is a real gap and was not previously recorded: a refreshed target updates
every operator-facing number immediately while the planner keeps proposing work against the
old list for up to `max_cycles_before_continuation` (100) cycles. (**M8-F7**)

The fix follows D-027's own precedent exactly: `measures_kpis` reached the workflow by
riding on the activity that already loads cycle context. `kpi_targets` should ride the same
way, which makes them a recorded activity result and keeps replay honest. **This is a
workflow-shape change and therefore not Lane A's to make** — and M8-3 (Lane C) is already
opening `CycleContext` for the pre-wake snapshot fix (M7-F45 / audit F-B). Folding it in
there is one field on a payload already being changed, versus a second workflow-shape change
later. Recorded as a cross-lane dependency, not decided here.

### 4.5 — Major versions, graduation, and a mechanism that does not exist

A-003 says a major version bump resets autonomy graduation counters: the action's behaviour
may have changed, so prior approvals no longer vouch for it. This is asserted in
`BusinessTypeRow.version`'s docstring, in `install_business_type`'s docstring, in
`BusinessTypeDefinition.major_version`, and in the version comments of both live type
modules, which each explain that their bump was *minor on purpose* so as not to trigger it.

**It is not implemented.** `AutonomyCounterRow.plugin_major_version` exists as a column with
a docstring stating the rule and has **zero readers and zero writers** in `jarvis/` or
`tests/`; it defaults to 1 and is never set from a definition. `BusinessTypeDefinition.
major_version`'s only consumer anywhere is one test assertion. `_reset_counter` is called on
correction, on denial, and on operator revocation — never on a version change. Nothing
compares an installed major version to anything.

This is the `KpiEngine.record` shape precisely (M7-F21: written in M3, callerless for four
milestones, found by a live run), and like it, **it is not in the deferred-completion
ledger**. (**M8-F8** — the ledger's second worked example of its own rule.)

Consequences for this design, and they are the reason the boundary is drawn here:

- **v1 refresh is minor-version-scoped.** The mechanism handles Band B for a minor bump. A
  major bump additionally implies A-003's reset, and implementing that reset is a
  graduation-state change — the packet's own escalation trigger. Part 7 escalates it.
- **The live migration is provably graduation-neutral.** Read from the live database: one
  `autonomy_counters` row exists in the entire system (Summit Trail Gear,
  `affiliate.publish_post`, `consecutive_approvals = 0`, `graduated = false`). Trailhead has
  no row. Portfolio Watch's type declares no autonomy policies at all. Nothing is graduated;
  nothing can be un-graduated. All three migrations in Part 5 are minor-version refreshes
  that touch no counter.

---

## Part 5 — Migration plan for the three live companies

Read from the live database read-only on 2026-07-27. All three are ACTIVE.

### Subject 1 — Portfolio Watch (`finance_tracking`, created 2026-07-26 21:52)

The F-A subject. Its stored `kpi_targets` have **no `direction` key** — the type was at
1.0.1 when it was created; 1.0.2 added direction.

**Diff:** `data_freshness_hours` gains `direction: below`. Nothing else moves —
`compliance_requirements` already carries all seven owner-approved rules; wake conditions
match; budget untouched.

**Effect, computed from the live `kpi_values` rows** (`metrics_tracked` 3 against target 5,
`data_freshness_hours` 0.0005 against 24, `reports_delivered` 3 against 4):

- before: (0.6 + 0.00002 + 0.75) / 3 → **45**
- after: (0.6 + 1.0 + 0.75) / 3 → **78**

This reproduces F-A's arithmetic exactly against live data, which is the correction's own
test. The goals drill-down also stops rendering "goal is at least 24 hours" for a
lower-is-better metric (M7-F62, ruled non-gating at M7 close and closed here as a
consequence rather than a patch).

### Subject 2 — Trailhead Gear Reviews (`affiliate`, created 2026-07-26 09:50)

The valuable one. Its stored `wake_conditions.event_triggers` are
`["approval.decided", "capability.result_returned"]`. The affiliate type removed
`capability.result_returned` at 1.0.1 as the M6-F10 fix — but the company predates the
installed fix and inherited the loop, exactly as M6-F22 predicted in writing.

**Diff:** `event_triggers` drops `capability.result_returned`. `kpi_targets` identical
(`posts_published` 20). `compliance_requirements` identical (5 rules). Budget untouched
($25.00 cap, $1.00 ceiling). No autonomy counter exists.

**Effect:** a live company stops being able to re-wake itself from its own output. This is
the first case of a refresh clearing a *defect* rather than a cosmetic staleness, and it is
the strongest argument that the refresh path is worth building. Safe: Trailhead retains two
wake paths (daily schedule, `approval.decided`).

**Verification:** the scheduler reads `event_triggers` off the contract per sweep, so this
takes effect on the next sweep with no Manager restart.

### Subject 3 — Summit Trail Gear (`affiliate`, created 2026-07-26 11:36)

**The negative control.** Created after affiliate 1.0.1 installed, so its snapshot is
already current: `event_triggers` is `["approval.decided"]` only.

**Diff: empty.** The refresh must produce "already up to date" and offer the operator
nothing. A blanket overwrite would look identical on subjects 1 and 2 and be indistinguishable
from a correct diff — Summit is what makes the mechanism's diff-driven nature falsifiable.

Summit additionally proves Band C: its `wake_cycle_ceiling_usd` is **$2.00**, an explicit
operator choice against the type's $1.00 suggestion (M6-F23's live vehicle). A refresh that
touched it would be a defect, and a test asserting it survives is the cheapest possible guard
on the whole of Band C.

### Sequencing

1. Land the installer work (Part 2) and the refresh mechanism (Part 4) behind no behaviour
   change — refresh offered, nothing applied.
2. Summit first: prove the empty diff and the surviving ceiling.
3. Portfolio Watch: prove the attainment correction end to end, 45 → 78, against real rows.
4. Trailhead last: the only one that changes runtime behaviour, and the one whose effect
   should be watched for a full sweep before the milestone claims it.

Each is an operator-consented action, so each is also a live rehearsal of the Part 6 surface.

---

## Part 6 — Operator surface (§8, §12.5)

Everything an operator sees from this design.

**The pending-update affordance**, on the company's own page. What it may say:

> **Trailhead Gear Reviews — an update is ready for this company.**
> The Affiliate publisher setup has changed since this company was created.
> - It will stop starting a new round of work when its own work comes back.
> *Review and apply* · *Not now*

**The vocabulary rules, which are gates, not style.** `tests/test_operator_language.py`
forbids seventeen terms in operator-facing text, and four of them are directly in this
feature's path: **capability**, **workflow**, **worker**, **business**. A diff renderer that
printed field names would emit `capability.result_returned` and `capability_permissions`
verbatim and fail the gate — correctly.

| Never render | Render instead |
|---|---|
| `capability.result_returned` in `event_triggers` | "stops starting a new round when its own work comes back" |
| "business type", "plugin", "definition", "manifest", "migration", "schema" | "company template", or the template's own display name |
| a version string (`1.0.1` → `1.0.2`) | "the setup has changed since this company was created" |
| `kpi_targets`, `direction: below` | "Data freshness — lower is better; this company was measuring it the wrong way round" |
| raw field names of any kind | a sentence per changed thing |

**Consequently the diff is rendered per changed *field*, from a platform-owned table of
sentences keyed on the field, filled from stored values — never a generic serializer, and
never model prose (D-011).** A field with no sentence in that table is not renderable and
therefore not refreshable; that is a feature, because it means a new Band B field cannot
reach an operator without someone writing the sentence.

**§8 relationship, stated plainly.** This is not an §8 approval and must not look like one:
it never appears in the approvals queue, never carries an amount, never graduates. §8 gates
what a company proposes to do; this gates what the platform proposes to change about a
company. Reusing the queue would put a graduation counter on configuration changes (4.3).

**M7-F12 note.** `scripts/gates.sh` gate 2 carries its own copy of the forbidden list, now
out of sync with the seventeen-term test list. Any packet adding operator surface here
should single-source it — the risk is a term the test forbids and the gate allows.

---

## Part 7 — What this design does not do

Escalations and deliberate non-decisions. Each is a decision the Manager or the owner makes,
not this packet.

1. **Refreshing `capability_permissions` or `autonomy_policies` (ESCALATION).** These are the
   authorization records `authorize_invocation` reads. A refresh that widened them would let
   a version bump grant an existing company new tool or credential reach with no human in the
   loop — a §10 boundary widening. A *narrowing-only* refresh (a type that removed a
   capability) is arguably safe and arguably the more dangerous half, because it silently
   disables work an operator is relying on. Frozen in v1; the decision belongs to
   security-engineer review with an owner-visible §8/§10 argument, not to a framework packet.
2. **Implementing A-003's major-version graduation reset (ESCALATION).** The mechanism is
   documented in four places, has a database column, and does not exist (4.5). Implementing
   it is a graduation-state change — the packet's stated escalation trigger. It needs its own
   packet, a deferred-completion ledger row, and a decision on whether the reset applies at
   install time or at the moment each company's refresh is accepted.
3. **A per-instance KPI target override surface.** M7-F3/M7-F24 confirmed it does not exist,
   and Band B's `target_value` rule depends on that. Building it is UI Phase 3 work, and it
   changes this design when it lands (M8-F6).
4. **The D-027 amendment questions** — metric semantics (M7-F33/F49), idle-cycle measurement
   (M7-F32), result-usefulness (M7-F60). They are about what a metric *means*; this document
   is about how a type's declaration reaches a company. Lane C, M8-5.
5. **The D-011 extension for feed prose** (M7-F50/F-C). Adjacent — the refresh diff is
   platform-rendered by exactly the discipline that debate is about — but the decision lives
   where its surface lives (UI Phase 4).
6. **Type removal and downgrade.** `remove_business_type` refuses while instances exist,
   which is correct and sufficient. Downgrade (installing an older version) is undefined; no
   finding requires it; not invented here.
7. **Cross-type dependencies, install ordering, a marketplace, an operator-uploaded type.**
   No demonstrated need. §14.

---

## Part 8 — Proposed decisions

Drafted for the Manager to write into `docs/DECISIONS.md` after review. Not written here.

- **D-029 — a business type's data reaches a company through three bands.** Band A is a live
  view refreshed by installation; Band B is a snapshot refreshed with operator consent; Band
  C is never refreshed. The line is authority, not convenience (4.1–4.2). Reversal cost:
  medium — the bands are a classification, but Band B's write path is real code.
- **D-030 — a contract refresh is consented on the company, never through §8's approval
  queue.** An `action_type` would give configuration changes a graduation counter (4.3).
  Reversal cost: low.
- **D-031 — the built-in catalog is an injected sequence, and that injection is the whole
  plugin extension path.** Install-time validation generalizes to the three checks with
  findings behind them; same-version drift is detected, never auto-installed (Part 2).
  Reversal cost: low.
- **D-032 — the type-parameter surface is closed and enumerated.** Part 1's two lists. A
  proposed type field requiring the platform to execute type-authored logic reopens D-014
  and is an escalation. Reversal cost: low — it records what is already true.

---

## Part 9 — Implementation packets this document cuts into

Proposed for wave 1, in merge order. Sizing is the Manager's.

| Packet | Content | Owner |
|---|---|---|
| A | Catalog move + injected sequence + `JarvisError` containment + audited skips + the three install-time validations (Part 2.1–2.4) | platform-engineer |
| B | Definition-digest staleness detector (Part 2.5) + `installed_at` refreshed on upgrade (M7-F48, one line, same file) | platform-engineer |
| C | `plan_refresh` / `apply_refresh` + the diff model + audit and Decision Log entries (4.4). No surface. | platform-engineer |
| D | The pending-update surface and the field-to-sentence table (Part 6) | operator-surface-engineer, product-reviewer gated |
| E | Live migration of all three companies in Part 5's order — this is M8-6 in the plan | platform-engineer + live proof |

**Cross-lane dependency:** `kpi_targets` into `CycleContext` (M8-F7) belongs in M8-3's
pre-wake snapshot work (Lane C), which is already changing that payload. If M8-3 has landed
before this is read, it becomes its own small workflow packet instead.
