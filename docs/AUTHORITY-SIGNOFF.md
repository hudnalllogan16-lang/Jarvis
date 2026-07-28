# Authority sign-off register

Every reduction of required authority in the platform is recorded here, by the owner, before
the pin that guards it is updated.

This file exists for exactly one purpose, and the narrowness is the point. A guard that fires
on *any* registry change — which `tests/test_action_registry.py` deliberately does — produces
two kinds of failure, and only one of them is a governance event:

- **Safe direction, or new surface.** A level raised, a threshold raised, an action added,
  eligibility switched off. The test says *"update the pin"* and nothing is recorded here.
- **An autonomy increase.** A level lowered, an approval rule relaxed, a graduation threshold
  lowered, or `graduation_eligible` switched on. The test says *"THIS INCREASES AUTONOMY —
  owner sign-off required"* and refuses to pass until the action appears in the table below.

## What this mechanism does and does not guarantee

It guarantees that **no autonomy increase is invisible.** It does not, and cannot, guarantee
that no autonomy increase happens: anyone able to edit `jarvis/domain/authority.py` can also
edit the pin and add a row here. Stating that plainly matters more than the guard sounding
strong — a security control whose reach is overstated is worse than one whose reach is known,
because work gets planned against the overstatement.

What it buys is that granting the platform more authority requires writing down, in an
owner-facing file that has no other content, *which* action was loosened, *from what to what*,
*who agreed*, and *why*. It cannot ride inside an unrelated diff, and it cannot be mistaken for
a refactor. That is the same protection D-011 gives an approval: the thing being defended is
the reviewer's attention, which is what an accidental ratchet actually attacks.

The threat model is design 1.6's, and it is not a bypass:

> A platform that may propose envelope changes, and whose proposals are usually good, trains
> its owner to approve them. The tenth approval is a reflex; the fiftieth is a rubber stamp.

A ratchet arrives through well-behaved changes with a tired human at the end of them. Forcing
each one to be named in isolation is what keeps the fiftieth from looking like the first.

## How to record a sign-off

1. Make the change in `jarvis/domain/authority.py` (or the declaring business type).
2. Run `bash scripts/gates.sh`. The failure message names every action whose authority moved
   and classifies the direction.
3. For each action reported as an autonomy increase, add a row below **with the owner**.
4. Update `REGISTRY_DIGEST_PIN` and `AUTONOMY_PIN` in `tests/test_action_registry.py`.

The action type in column one must be in backticks — that is what the test parses.

## Register

| Action | From | To | Owner | Date | Reason |
|---|---|---|---|---|---|
| *(none)* | | | | | The registry has never had an authority level reduced. |

**Read the emptiness as evidence, not as an untested guard.** The direction classifier and the
sign-off parser are both exercised by negative controls in `tests/test_action_registry.py`
(`test_the_ratchet_detector_classifies_direction_correctly`), per M8-F120's discipline: a gate
that has never failed is indistinguishable from a gate that cannot fail.
