## Packet M9-8: pre-tag audit fixes (F1, F4 + F2/F3 sentences)

**Agent:** security-engineer  **Model:** sonnet — three small, exactly-specified fixes from
the M9 audit. Findings **M9-F185–F189**. Lane: `lane/m9-8`.

1. **F1 (governance violation, blocker):** `_refuse_unauthorised_action_types` must raise
   `ConfigurationError` when `granted_entry(...) is None` — an unregistered action type
   refuses install. Test + negative control (registered still installs); the built-ins still
   install (they''re registered).
2. **F4:** value pins on the three M9-F130 remediation rows — assertions that
   `max_cycles_per_day == 48`, `max_invocation_budget_usd`''s current value, and
   `graduation_eligible is False` match what the register and remediation table state; a
   drift fails with a message naming the table.
3. **F2/F3 (one sentence each, docs):** EXECUTIVE-GOVERNANCE.md Part 1.4 gains the two
   explicit exclusions — contract refresh executes under D-030 outside the graduation-keyed
   registry BY DESIGN (its authority is the operator''s consent, recorded per-apply), and
   `platform.install_business_type` is performed automatically ONLY for the repo-shipped
   injected catalog (the injection point is the convention''s boundary, F3''s sentence).
Gates exit 0; commit "M9-8: "; never merge/push; no DECISIONS.md edits. Report 250/400.
