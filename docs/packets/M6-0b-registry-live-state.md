## Packet M6-0b: dispatch authorization must read live lifecycle state

**Agent:** security-engineer   **Model:** opus — authorization path, security boundary (D-002
territory), a plausible mistake lets dispatch bypass lifecycle gating; gates cover the intended
behaviour but not every way to get it wrong.

**Objective**
`Registry.authorize_invocation` evaluates dispatch acceptance against the business's *current*
lifecycle state, so that the 13 tests failing on spurious `not_dispatchable` pass without any
test being weakened.

**Files in scope**
Read first:
- `jarvis/registry/registry.py` — the defect is at `authorize_invocation` (~line 360): it calls
  `resolve_identity(business_id)` and derives `LifecycleState` from the returned contract. That
  contract is reconstructed from the JSON snapshot written once at `register_instance` and never
  updated by `transition()`, which updates only the `BusinessInstanceRow.lifecycle_state` column.
  So the check always sees the registration-time state (`PROVISIONING`) and denies everything.
- `tests/test_capability_pool.py`, `tests/test_registry.py` — the tests that document intended
  behaviour. Do not edit them.

Edit:
- `jarvis/registry/registry.py` only — read live state (e.g. via `get_state()`) instead of the
  stale contract field. Keep the check's position in the rejection order: identity mismatch is
  checked before dispatchability, and `not_dispatchable` before capability/tool/credential scope
  checks — `test_every_rejection_path_is_audited` encodes that order.

**Context you need**
D-002 (quoted): "The `business_id` on an inbound scoped request is advisory and ignored for
authorization. The capability pool derives the true invoking identity from the Temporal
workflow's registered business identifier, resolves it through the Business Registry, and
validates the requested memory / credential / tool scopes against that business's configured
capability-invocation permissions. Any mismatch is rejected and audited — never narrowed, never
silently corrected."

D-008 defines the lifecycle state machine; `accepts_dispatch` is its property. The defect fails
closed today; your fix must not make any rejection path *more* permissive than the tests assert.

**Acceptance criteria**
- [ ] `uv run pytest -q` — the 13 previously failing tests pass; no previously passing test regresses
- [ ] `bash scripts/gates.sh` exit code improves to 0, or any remaining failure is exactly the
      known M6-0c health-band failure (`test_stuck_work_dominates_the_score`) or a lint/format/
      pyright step failing on code you did not touch — report either verbatim
- [ ] The stale-contract read is gone from the authorization path; no other behaviour changed

**Out of scope**
The health-band failure (packet M6-0c). Fixing `transition()` to also rewrite the contract JSON
(that is a design question about whether the snapshot should ever be current — if you believe it
should, say so as a follow-up, don't do it). Any change under `tests/` or `migrations/`.

**Escalate instead of deciding if**
- Reading live state requires changing a public interface or adding a query the Registry doesn't have
- You find any *other* consumer of the stale snapshot making authorization or budget decisions
- The rejection-order the tests encode conflicts with what you believe D-002 requires
