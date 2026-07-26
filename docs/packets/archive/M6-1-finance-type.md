## Packet M6-1: Finance Tracking business type

**Agent:** business-type-author   **Model:** sonnet — the correctness criterion is
mechanically checkable (data-only AST gate, prompt coverage, registry round-trip), blast
radius is one new module, reversal is deleting a file.

**Objective**
Add the Finance Tracking business type as pure configuration, proving D-014 holds for a
second type without any change to the generic machinery.

**Why this packet matters beyond the feature**
This is the test of D-014. If adding this type requires touching `jarvis/manager/`,
`jarvis/businesses/definition.py`, or `jarvis/businesses/provisioning.py`, then business types
are not really data and the Manager is not really generic. **Any such need is an escalation,
not something to work around.** A clean pass is the evidence; a blocked packet is also a
useful result.

**Context you need**
Spec §13 Step 3 places Finance Tracking second because it is read-only and lower-risk than
publishing: it reads financial data, computes and reports, and does not move money. It
exercises the KPI and dashboard path rather than the effect-performing path.

D-014: a business type is data. Zero functions, zero classes in the type module —
`tests/test_affiliate_type.py` asserts this against the AST and your test must do the same.

Spec §8: approval by default; anything touching money is never graduation-eligible. This type
should have *no* effect-performing tool and *no* capital action at all. If you find yourself
giving it one, you have misread the milestone.

**Files in scope**
Read first:
- `jarvis/businesses/affiliate.py` — your module has the same shape
- `jarvis/businesses/definition.py` — the fields available to you (read only; do not edit)
- `tests/test_affiliate_type.py` — your test mirrors this
- `jarvis/events/types.py` — the only event types you may subscribe to

Create:
- `jarvis/businesses/finance.py`
- `tests/test_finance_type.py`

**Acceptance criteria**
- [ ] `jarvis/businesses/finance.py` contains zero functions and zero classes (AST-asserted)
- [ ] Every permitted capability has a prompt template keyed `finance.{capability}`
- [ ] No capability grants an effect-performing tool; no action carries an amount
- [ ] `event_triggers` ⊆ the constants in `jarvis/events/types.py`
- [ ] Explicit wake ceiling and business cap (Defaults in Force requires the ceiling)
- [ ] `compliance_requirements` are real and specific to financial reporting — accuracy,
      provenance of figures, no advice framing, owner sign-off before launch
- [ ] `tests/test_finance_type.py` mirrors the affiliate suite: data-only, prompt coverage,
      registry-metadata round trip, approval-required-from-day-one, explicit ceiling
- [ ] `bash scripts/gates.sh` passes
- [ ] `ensure_builtin_types` installs it (check whether that needs a one-line addition; if it
      needs more than one line, escalate)

**Out of scope**
Any change to `jarvis/manager/`, `definition.py`, or `provisioning.py`. Live data sources or
real financial APIs. Dashboard changes (packet M6-3).

**Escalate instead of deciding if**
- The definition schema lacks a field this type genuinely needs
- Installing or instantiating it requires a code change outside your module
- A capability you need doesn't exist in `CapabilityType`
- The type seems to require logic to be useful
