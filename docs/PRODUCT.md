# Product Objective

This is the product constitution for Jarvis, the counterpart to the Architecture Specification.
The spec governs whether the system is *correct*; this governs whether it is *delightful to
operate*. The `product-reviewer` agent holds this on the Manager's behalf, the way the
`architecture-auditor` holds the spec.

It is durable memory. It does not change as milestones pass; it is the fixed standard they are
measured against.

---

## The objective

**Jarvis must eventually feel like premium desktop software.** Not merely functional. Not merely
technically impressive. Premium.

The current UI is deliberately a prototype. It exists to prove functionality, and it is doing
that job. **It is not the visual direction of the product**, and it should not be mistaken for
it. That distinction matters in both directions: the prototype is allowed to look plain, and it
is not allowed to be confusing, to dead-end, or to obscure what Jarvis is doing.

## The feeling

The interface should feel calm, intelligent, modern, confident, information-rich, deliberate,
and polished.

The operator should feel they are **operating intelligent companies, not configuring software.**
Everything follows from that sentence:

- **Automation should feel visible.** The operator should see Jarvis working, not wonder whether
  it is.
- **The interface should explain itself.** Understanding should not require documentation.
- **Errors should guide recovery.** A failure states what happened and what to do next, never
  just what broke.
- **Empty states should teach.** A screen with nothing in it yet is the best moment to show the
  operator what will appear and how to begin.
- **The dashboard should be the operational centre.** It answers, at a glance, the first
  question an operator has: *what is Jarvis doing right now?*

## §12.5 is a product principle, not only a rule

The operator-language gate (`tests/test_operator_language.py`) enforces vocabulary. But the
reason behind it is a product reason: an operator runs companies and should never be made to
think about workflows, agents, or retries. The gate catches the words; the product review
catches the moments the *experience* still feels like operating a machine rather than a business.

## The emotional target

**"It feels like operating Iron Man's JARVIS."** Calm competence. The system is doing a great
deal; the operator feels in command of it rather than buried by it. When a surface feels busy,
uncertain, or inert, that is the standard it has fallen short of.

---

## Inspiration — study, don't imitate

The goal is not to copy the look of any product. It is to understand what makes excellent
software excellent, and to apply the understanding. Worth studying:

- **Linear** — information hierarchy and restraint; how much is conveyed with how little.
- **Arc** — confident, unconventional structure that still feels obvious.
- **Raycast** — speed and keyboard-first density without clutter.
- **Cursor** — surfacing an intelligent system's activity legibly.
- **Notion** — progressive disclosure; simple surface over deep capability.
- **Apple desktop applications** — spacing, typography, and the feel of a native app.

What to take from them: information hierarchy, typography, spacing, interaction quality,
cross-screen consistency, confidence, restraint. What not to take: their specific colours,
components, or layouts. The point is the principles, not the appearance.

---

## Where product sits in the roadmap

Correctness comes first, always. But once correctness exists, product quality is a **first-class
engineering objective, not an optional enhancement.** The standing priority order:

1. **Platform correctness** — it does the right thing, safely.
2. **Complete vertical slices** — whole paths work end to end, not just layers in isolation.
3. **Workflow refinement** — the operator's actual tasks are smooth.
4. **Product experience refinement** — it becomes genuinely good to use.
5. **Commercial-quality polish** — it becomes premium.

A milestone does not reach for tier _n_ before tier _n−1_ holds. This is why the prototype UI is
correct *for now* and also why "make it premium" is a real objective rather than a someday-wish:
it has a defined place in the sequence, and product review becomes a milestone gate the moment a
milestone has an operator-facing surface.

---

## Governance

Product governance runs parallel to architectural governance, with the same shape:

|  | Architecture | Product |
|---|---|---|
| Reviewer | `architecture-auditor` | `product-reviewer` |
| Asks | Is the system correct? | Is it delightful to operate? |
| Reports to | The Engineering Manager | The Engineering Manager |
| Edits code? | Never | Never |
| Makes implementation decisions? | Never | Never |
| Gates a milestone | Any milestone touching architecture | Any milestone with an operator-facing surface |

Both reviewers are independent and read-only by design: they report findings, and the Manager
decides what to do about them. Neither is a substitute for the other — a milestone with both an
architectural surface and a product surface needs both verdicts before it is complete. This is a
permanent part of the Claude Code engineering process, not a one-time review.
