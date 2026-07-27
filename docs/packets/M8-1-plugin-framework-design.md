## Packet M8-1: plugin framework design (Lane A, wave 0)

**Agent:** platform-engineer   **Model:** opus — the highest-blast-radius design since M1;
Tier C (Manager reads the output; auditor gates implementation). Finding range: **M8-F1–F19**.
Lane: `lane/m8-1`.

**Objective**
A design document — `docs/design/PLUGIN-FRAMEWORK.md` — plus proposed D-entries (in your
report, NOT written to DECISIONS.md) that resolve, coherently and minimally, the four framework
questions M6/M7 accumulated. **Design only; implementation packets are cut from your document
after Manager review.** Code changes limited to throwaway probes in your lane (never merged
logic).

**The four questions (context in DECISIONS.md — read D-014, D-027, D-028, M6-F22, M7-F1/F4,
F-A, M7-F24/F62, M7-F36 first):**
1. **Installer generalization (M7-F1):** from `BUILTIN_TYPES` tuple to a discovery/
   registration mechanism that §4's wizard-installable future can use — without speculative
   machinery (§14: the demonstrated need is two built-ins and the M10 Trading Analysis type;
   design for three, note the extension path, build no plugin marketplace).
2. **Contract-refresh-on-upgrade (F-A/M7-F62/M7-F24):** when a type version bumps, what
   propagates to existing companies' contracts (KPI targets/direction? wake conditions?
   compliance text? prompts?), what never does (budget caps? graduation state — D-010/A-003
   interplay), who approves (does a refresh need the operator's OK per §8's spirit?), and how
   the three live companies migrate. This is the hard one — treat stored-contract-as-snapshot
   vs contract-as-view head on.
3. **Type packaging (§4):** what a business type IS as an artifact (module? directory with
   prompts/templates? versioned manifest?) such that M10's Trading Analysis — a genuinely
   complex type — installs "through configuration only". Reconcile with D-014's data-only gate.
4. **What M7 proved:** the design must cite the M7 evidence (three data-shaped generic
   changes) and state which parts of the platform are now type-parameter surface vs frozen.

**Acceptance criteria**
- [ ] The design doc exists, complete, with a migration plan for the 3 live companies and an
      explicit §8/§12.5 operator-surface note for anything the operator will see
- [ ] Proposed D-entries drafted in the report (Manager writes them after review)
- [ ] Gates exit 0 (docs-only expected); report bounded (450/600) with findings M8-F1–F19

**Escalate instead of deciding if** any resolution would change a MUST/MUST NOT (spec v1.5),
alter D-001…D-028 semantics, or require touching graduation/approval state during migration.
