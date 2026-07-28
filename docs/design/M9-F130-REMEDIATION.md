# M9-F130 Remediation Table

**Status:** draft, for the owner's retroactive blessing at ratification. Part of
the M9-G1b deliverable (design `EXECUTIVE-GOVERNANCE.md` Part 3.3, G1-parameters).
**Implements nothing. Changes no live contract.** This document only enumerates
what the platform is already doing, so the owner can rule on it once, in one
place, rather than meeting each violation separately as a finding.

## Why this table exists

Under the owner's origin clause (`EXECUTIVE-GOVERNANCE.md` Part 2.1, ratified
verbatim): *"Policies may only originate from: Owner, Approved specifications,
Approved configuration."* Three ENFORCING parameters — values that gate what the
platform may do — currently have Provenance Origin `PLATFORM_DEFAULT`, which is
not one of the three. Under revision 1 these were hygiene findings. Under the
owner's own definition, enforcing them **is enforcing something no one
authorised** (`EXECUTIVE-GOVERNANCE.md` Part 2.1, **M9-F130**).

The M9-G1b packet's mandate is to enumerate, not to fix: "implement nothing,
change no live contract." Registering these in
`jarvis/registry/parameter_register.py::KNOWN_M130_EXCEPTIONS` and here is what
lets `tests/test_parameter_register.py` hold the origin-clause invariant for
every *other* ENFORCING parameter today, without either silently accepting
these three or unilaterally changing platform behaviour that a business is
currently running against.

## The three illegitimate constraints

| # | Finding | Parameter | Current value | Where it lives | Origin today |
|---|---|---|---|---|---|
| 1 | M9-F117 → M9-F130 | `WakeConditions.max_cycles_per_day` | `48` | `jarvis/domain/contract.py`, `Field(default=48)` | `PLATFORM_DEFAULT` |
| 2 | M9-F117 → M9-F130 | `CapabilityPermission.max_invocation_budget_usd` | `$0.50` | `jarvis/domain/contract.py`, `Field(default=Decimal("0.50"))` | `PLATFORM_DEFAULT` |
| 3 | M9-F115 → M9-F130 | `AutonomyPolicy.graduation_eligible` | `True` | `jarvis/domain/contract.py`, `bool = True` | `PLATFORM_DEFAULT` |

Each is registered in `jarvis/registry/parameter_register.py::PARAMETER_REGISTER`
as `ParameterClass.ENFORCING`, and is named exactly (not approximately) in
`KNOWN_M130_EXCEPTIONS`, so a *new* ENFORCING parameter carrying an illegitimate
origin cannot hide behind these three — `test_enforcing_violations_are_
exactly_the_known_m130_exceptions` fails on any set other than this one.

## The persisted default — worse than a code default alone

`max_cycles_per_day = 48` is not merely a code default: `EXECUTIVE-GOVERNANCE.md`
Part 0.1 and Part 5.2 record it read, live and read-only on 2026-07-28, as the
**stored** value in all three live companies' contract JSON —

| Company | `max_cycles_per_day` (stored) |
|---|---|
| Trailhead Gear Reviews | 48 |
| Summit Trail Gear | 48 |
| Portfolio Watch | 48 |

— meaning the platform has persisted a policy value nobody authorised into the
operator's own data, not merely defaulted it in memory. Against the platform's
own live spend rate (`EXECUTIVE-GOVERNANCE.md` Part 5.2, **M9-F119**), this
ceiling permits each company several times its entire lifetime reserve in a
single day. No contract is rewritten by this document or by the M9-G1b packet:
correcting the stored value is itself an L3 act (`ceiling / window change`,
Part 1.4) and belongs to the owner, not to a governance-enumeration packet.

## What ratification is being asked to decide

For each of the three rows above, one of:

1. **Ratify as `APPROVED_CONFIG`** — the owner reviews the current value, judges
   it correct, and its Origin becomes legitimate by the owner's own act of
   review. No value changes; only its Origin does.
2. **Direct a new value** — the owner sets a different number, which is then
   `APPROVED_CONFIG` from the moment it is set. This is the only path that
   touches the live contracts, and it requires the owner's explicit choice of
   value, not this document's.
3. **Leave unresolved** — the exception stays open, visibly, in
   `KNOWN_M130_EXCEPTIONS` and in this table, rather than being quietly
   absorbed into "how things are." The platform continues enforcing the
   current values in the meantime; nothing here pauses or refuses on their
   account.

Whichever the owner chooses, the record this table and `KNOWN_M130_EXCEPTIONS`
keep is the same: three values are enforced today with Origin `PLATFORM_DEFAULT`,
one of them additionally persisted into every live company's own data, and no
one before this packet had written that down in one place.
