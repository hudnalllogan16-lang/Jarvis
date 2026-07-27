# M8 Strategic Review and Execution Plan

Status: awaiting owner approval. No implementation dispatched. Sources: the complete M6/M7
execution records (DECISIONS.md D-001–D-027, findings M5-F*…M7-F69, both milestone reports,
both verdict sets, the D-026 org report and its measured pilot), the dependency graph, and
the owner's Premium UI Concept (product direction reference).

---

## Part 1 — The engineering evidence (M6/M7 as data)

**Discovery rate.** M6: 6 planned packets became 15 executed (+ reviews) — multiplier ~2.5×.
M7: 4 planned became 9 (+ OPS-1) — ~2.2×. Findings per packet held steady at 4–5. Conclusion:
the 70%-capacity rule is calibrated correctly and stays; static plans that book 100% will
always be wrong here.

**Merge cadence and gate utilization.** Ten worktree lanes, ten merges, zero conflicts, and
**zero post-merge main-gate failures** — composition never broke, which is direct evidence the
ownership boundaries in packets are drawn correctly. Gates run ~2× per packet (lane + main);
suite runtime ~2–3 min at 734 tests is nowhere near binding.

**Review effectiveness.** Every single review round found real defects, and the two reviewers
never overlapped once across four verdicts (M6: blank dashboard vs approval-payload
invisibility; M7: unrendered KPIs vs direction-not-applied). The two-reviewer split is
validated conclusively. Warm re-review passes cost 3–10× less than cold reviews (final M7
verdict: ~95 seconds) — warm resumption graduates from technique to default.

**Escalation quality.** Five formal escalations across two milestones; zero false stops; every
one produced a D-entry or a scheduled design item. The escalate-don't-guess culture is paying
for itself and needs no tuning.

**Specialization load.** M6 was security-heavy (7 packets); M7 shifted to workflow (4) and
surface (3+2 REVISE rounds). Model routing held: no sonnet packet needed an opus rescue; no
audit found an under-provisioned worker. One pattern is new and load-bearing: **all five
product REVISE rounds across both milestones targeted UI surfaces** — the surface is where
quality pressure concentrates, and it is about to become a standing program (Part 5).

**Architecture churn.** Near zero: two composition-root edits and two data-shaped contract
fields in M7, all audit-endorsed. No invariant weakened in ~140 merged commits. D-019's
"stable by default" is working.

**Serialization audit.** Necessary and kept: the merge queue (its determinism is why
composition never broke), REVISE loops (inherently serial, cheapened by warm resumption),
discovery chains. Unnecessary and addressed: none found beyond what D-026 already fixed — the
Manager remains the intentional serialization point, and at 2–3 lanes it never became the
queue. One cheap process improvement supported by evidence: operator-surface packets gain a
**pre-report §12.5/product self-check** (label-vs-content agreement, scales, null states,
escaping) — three of five REVISE rounds caught defects that checklist would have caught in
lane.

## Part 2 — Dependency graph, reworked for M8

Roadmap order is not implementation order. The real graph from here:

- **Critical path:** plugin framework design (installer generalization M7-F1 +
  contract-refresh-on-upgrade F-A/M7-F62 + type packaging) → M10 Trading Analysis → M12.
- **Independent stream 1 — Premium UI initiative:** zero dependency on the plugin framework.
  Its Phases 1–2 (design system, application shell) can start immediately; Phase 3 (business
  workspaces) consumes type display metadata that already exists.
- **Independent stream 2 — platform hardening:** pre-wake snapshot staleness (M7-F45/F-B),
  **workflow versioning (M6-F33 — the standing pre-production requirement, and M8 is its
  natural home: the plugin framework will change workflow-adjacent code, which is exactly when
  versioning discipline must exist)**, the resilience ledger (M6-F13/F17/F18/F42, D-025.2
  remnant), and the D-027 amendment pass (metric semantics F33/F49, idle measurement F32,
  result-usefulness F60).
- **Available early but deliberately deferred:** M9 Executive Layer deterministic rollups
  (both prerequisites exist — two business types). Deferred purely on capacity; recorded so
  the deferral is a choice, not an omission. M9 remains parallel-safe with M8 per the graph's
  own no-edge note.

## Part 3 — Organization for M8: three lanes, evidence-based

Three concurrent lanes are justified **by M8's actual wave-0 content, not by availability**:
the three streams above are genuinely independent, each a full lane's sustained work. This is
the first milestone whose shape supports 3 lanes; M7's shape supported exactly 2, and 2 was
correct then.

- **Lane A — Plugin framework** (critical path): platform-engineer default, opus on
  design-heavy packets (installer/type-packaging design, contract-refresh).
- **Lane B — Premium UI program:** the new experience-engineer (Part 4), product-reviewer
  gating each phase per the owner's directive.
- **Lane C — Hardening:** workflow-engineer (F45, F33 first — both touch workflow code and
  should land BEFORE the framework churns it), then the D-027 amendment pass.

**Coordinator activation.** With 3 lanes and pre-written packets, the delivery-coordinator's
designed use-case exists for the first time (2+ prepared packets, mechanical dispatch).
Activate it for wave execution; escalations still bypass it verbatim; the reviewers still
report only to the Manager. Merge queue, serial-resource allocation, finding ranges, 70% rule:
all unchanged.

## Part 4 — Agent roster: one addition, evidence-backed

**Add `experience-engineer`** (design system, application shell, workspace layout, motion,
interaction density — the premium-software craft). Evidence: five of five product REVISE
rounds were surface defects; the UI initiative is a standing multi-milestone program with a
different skill center than operator-surface-engineer's §12.5-copy-and-rendering-boundary
focus. The two divide cleanly: experience-engineer owns structure/system/visual language;
operator-surface-engineer keeps operator copy, D-007 translation, rendering boundaries, and
the §12.5 conscience. Sonnet default, opus for the design-system foundation packet.

**Declined for lack of evidence** (per the owner's own bar): performance (no measured
performance finding exists), dedicated plugin-framework engineer (platform-engineer's
territory, no overload signal), infrastructure (OPS-1 was one packet), documentation beyond
docs-writer (working well), dedicated tester (test-engineer utilization is healthy).

## Part 5 — Premium UI implementation roadmap

The concept image is adopted as the **quality bar and design language** — executive command
center, calm dark surface, stat tiles, per-company cards with trends, activity feed, approval
cards with compliance chips, system health made glanceable. Not adopted pixel-for-pixel; every
screen maps to what Jarvis actually does today.

**One conflict requires an owner ruling before Phase 2 ships (flagged, not resolved):** the
concept surfaces **named Managers** ("Stella", "Orion", "Active Managers: 3", a "Managers" nav
item). Spec §12.5's binding translation table says the Business Manager is *invisible* —
"represented as the Company's activity/status, not a named entity." Personifying managers may
be excellent product (it is very Sims-like, which §1 wants), but it contradicts the table as
written. Options: (a) amend §12.5/D-007 to permit named manager personas (owner's §12
amendment, one row change); (b) keep managers invisible and render those surfaces as company
activity. The UI plan below is compatible with either; nav and copy decisions that depend on
it sit in Phase 2 and will follow whichever you rule.

**Phasing (each phase product-reviewed before the next begins, per your directive):**

1. **Design system** — tokens (type scale, spacing, color incl. the existing health/risk
   semantics, dark-first), the component set the shell needs (tiles, cards, feeds, badges,
   meters), animation principles, accessibility standards (contrast, focus, reduced-motion),
   and the decomposition of the `index.html` monolith into modules — the split that B7
   deferred "until a surface milestone justifies it"; this is that milestone. **Named open
   decision:** whether to stay dependency-light (modular vanilla/web components) or adopt a
   build-step framework — Phase 1 starts dependency-light and the Phase-2 retrospective
   decides with evidence; adopting a build system is a tooling decision the owner hears about
   first either way.
2. **Application shell** — sidebar + top nav, the Command Center layout (stat row, companies,
   feed, approvals, health), notification center, responsive behavior. All content is real:
   every tile in the concept maps to data Jarvis already serves (companies, cycles as
   "actions", approval rate, model spend from the ledger, milestone status from nothing —
   that one is dev-only chrome and gets an operator-honest equivalent or gets dropped).
3. **Business workspaces** — per-company operational pages: status, KPIs
   (measured-vs-target, the M7 drill-down grown up), health with components, execution
   history, approvals scoped to the company, trends. Consumes plugin-framework metadata as
   Lane A lands it.
4. **Workflow experience** — approvals flow, audit drill-down, notifications, transitions,
   micro-interactions; the D-011-extension question (platform-rendered narrative vs guarded
   model prose, M7-F50) is decided HERE, where its surface lives.
5. **Polish** — motion, consistency, perceived performance, accessibility audit.

M8 scope is Phases 1–2 complete + Phase 3 begun once framework metadata exists; 3–5 continue
into M9/M10 alongside platform work — the UI evolves with the platform, per the directive.

## Part 6 — M8 execution plan

**Wave 0 (3 lanes, parallel):**
- **M8-1** (Lane A, platform-engineer, opus): plugin framework design packet — installer
  generalization (M7-F1), type packaging/discovery shape, contract-refresh-on-upgrade design
  (F-A/M7-F62/M7-F24). Design + D-entry proposals first, implementation packets cut from it.
- **M8-2** (Lane B, experience-engineer, opus for the foundation): design system (UI Phase 1)
  + monolith decomposition, product-reviewer gate at completion.
- **M8-3** (Lane C, workflow-engineer, opus): pre-wake snapshot fix (M7-F45 full scope) +
  workflow versioning convention (M6-F33) — landing before Lane A churns workflow code.

**Wave 1:** M8-1's implementation packets (installer + refresh mechanism + migration of the
two live types); M8-4 UI application shell (Phase 2, gated on the §12.5 Managers ruling for
nav/copy); M8-5 D-027 amendment pass (Lane C).

**Wave 2:** M8-6 re-install/upgrade live proof (all three companies migrate through the real
refresh path); M8-7 workspace foundations (UI Phase 3 start); resilience remainder
(M6-F13/F17/F18) as capacity allows under the 70% rule.

**Wave 3:** architecture audit + product review (parallel, gating), REVISE round, close-out,
`m8-baseline`.

**Merge order per wave:** hardening → framework → UI → docs. Finding ranges allocated at
packet-writing. Reviewers: unchanged pair; product-reviewer additionally gates each UI phase.
**Risks, named:** framework design is the highest-blast-radius work since M1 (audit depth:
Tier C, Manager reads code); UI stream churns the file every surface packet touches (the
monolith split in M8-2 is the mitigation and lands first); three lanes is a first (the
coordinator absorbs dispatch mechanics; the Manager watches for queue formation and drops to
2 if merge latency grows); the §12.5 Managers ruling gates Phase-2 copy (needed by wave 1).
**Spend:** framework live proofs + UI screenshots ≈ $5–10 cap.

**Success criteria (the owner's two, made checkable):** (1) a third business type installable
through the framework with zero composition-root edits — proven by the Trading Analysis
*type shell* installing cleanly in a test; (2) the operator experience at M8 close judged by
the product reviewer against the concept's standard — Phases 1–2 SHIP-verdict quality, with
the M7 dashboard's information preserved and elevated, nothing regressed.

---

## Requested from the owner
1. Approval of this plan (or edits).
2. The §12.5 ruling: named Manager personas (spec amendment) vs invisible-manager rendering.
3. Confirmation that adding `experience-engineer` to the roster is approved (one new agent
   definition file, charter per Part 4).
