## Packet M8-1b: catalog, validation, containment, drift (framework packets A+B)

**Agent:** platform-engineer   **Model:** sonnet — the design is decided (D-031), gates and
the design doc cover correctness. Finding range: **M8-F60–F69**. Lane: `lane/m8-1b`.

**Objective**
Implement docs/design/PLUGIN-FRAMEWORK.md Parts 2.1–2.5 exactly: `BUILTIN_TYPES` moves to
`jarvis/businesses/catalog.py`; `PlatformKernel` takes the catalog as an injected sequence;
install containment catches the errors installs actually raise (M8-F1 — `JarvisError`
breadth per the design), skipped installs are audited not silent (M8-F2); the three
install-time validations land; the definition-digest staleness detector (Part 2.5) detects
same-version drift (M8-F3's live case will light up — detection only, NEVER auto-install);
`installed_at` refreshes on upgrade (M7-F48).

**Constraints:** the design doc is authoritative — deviations are escalations, not
improvisations. D-014 gate, layering gate, both replay fixtures untouched. Live DB read-only
(the drift detector will flag live affiliate v1.0.1 — that's expected and belongs in your
report, not fixed here; packet C's refresh handles it). $0.

**Acceptance:** gates exit 0; tests before → after; drift detector proven both directions
(clean type silent, drifted type flagged with an audited, operator-safe record); containment
proven by a poisoned-catalog test (one bad type, others install). Report 350/500.

**Escalate if** the design's validation trio can't be implemented without touching
provisioning semantics, or containment requires error-hierarchy changes beyond the design.
