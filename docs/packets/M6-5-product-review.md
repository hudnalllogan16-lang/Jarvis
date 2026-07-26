## Packet M6-5: product review of the vertical slice

**Agent:** product-reviewer   **Model:** opus, effort high — experience judgement no gate can
make; runs in parallel with the architecture audit (M6-4), not after it.

**Objective**
Review the operator experience of the complete Affiliate slice and return a ship verdict.

**Why this exists**
M6-4 asks whether the slice is *correct*. This asks whether it is *good to operate*. A slice can
be architecturally clean and still confuse the operator at the first approval, or dead-end them
when a company has nothing to show yet. Both verdicts gate M6.

**Context you need**
Your constitution is `docs/PRODUCT.md` — read it first. The objective is premium desktop
software; the current UI is a functional prototype, so judge movement toward the objective, not
arrival. The prototype may look plain; it may not confuse, dead-end, or hide what Jarvis is
doing.

M6 is the first milestone where a *whole transaction* is walkable, so the experience of the flow
— not just individual screens — is reviewable for the first time.

**What to walk** (run the app read-only; change nothing)
- First run: nothing created yet. Does the empty state teach what to do?
- Creating the first company: how many steps, how much thinking required?
- A company running: does the dashboard answer "what is Jarvis doing right now?"
- An approval arriving: are §8's four facts clear? Does the operator understand what they're
  approving and the downside?
- Approving, then the action executing: does the operator see it happen and land?
- An error along the way: does it guide recovery or just report failure?

**Deliverable**
A design review, not a code review. One verdict — SHIP / SHIP WITH FOLLOW-UPS / REVISE — with
findings naming the screen, the moment in the flow, and what the operator experiences. Describe
problems and desired outcomes; leave implementation to the Manager. No pixel or colour
prescriptions.

**Out of scope**
Implementing any fix. Redesigning the dashboard. Aesthetic preferences unmoored from experience.
Architecture (that's M6-4).
