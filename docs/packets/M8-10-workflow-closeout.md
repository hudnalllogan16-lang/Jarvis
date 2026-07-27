## Packet M8-10: workflow closeout — F87, F88, D-035 mechanism

**Agent:** workflow-engineer   **Model:** opus — continuation model + cancellation +
wake-reason semantics under D-033 discipline. Finding range: **M8-F130–F139**.
Lane: `lane/m8-10`.

**Three items, all decided (DECISIONS.md D-035 block):**
1. **M8-F87:** `cycles_completed` resets at continue-as-new so `CYCLES_BEFORE_CONTINUATION`
   binds every generation — D-005 state shape; mind what else derives from the ordinal
   (the D-034.2 cycle key namespaces by run id, so keys stay unique — assert it).
2. **M8-F88:** `CapabilityPool._execute_with_retry` gains the cancellation handler
   `_ask_model` already has — a cancelled dispatch releases its hold; test with the
   reconcile's negative control (the orphan case that no longer needs the age backstop).
3. **D-035:** the non-dispatchable wake path emits the "answered approval waiting"
   notification + audit record for dropped decided-approval reasons (copy key only —
   M8-9 owns the words; use the notification service's stored-values path). Park path
   deliberately unchanged.

D-033: any live-path change behind a `PATCH_*` id with per-fixture replay proof — item 3
touches the wake loop; items 1–2 assess and state whether recorded-result gating suffices
(the D-033 test's own rule). Gates exit 0; both fixtures; $0; live DB read-only.
Report 350/500.

**Escalate if** the ordinal reset breaks any recorded-result consumer, or D-035's
notification can't be emitted from the workflow side without a new activity (if it needs
one, that's fine — say so and add it under the frozen-inventory test's discipline).
