# 01 — Design Principles

Six principles. Each is a rule that can be *lost* — if a principle cannot be violated by a
plausible design, it is a slogan, not a principle. Each therefore names what violating it looks
like.

---

## 1. The operator supervises companies; they do not monitor software

From `docs/PRODUCT.md`: *"operating intelligent companies, not configuring software."* Every
surface answers a question an owner would ask about a business — what is it doing, is it
healthy, what does it need from me, what did it spend — and never a question about the machine.

**Violation looks like:** a queue depth, a job state, a progress percentage of an internal
process, a "last sync" timestamp, a retry counter. Also: an empty state that says "no data"
instead of teaching what will appear here.

This is the design-side statement of spec §12.5, which the static gate enforces mechanically.
The gate catches vocabulary; this principle catches *shape* — a surface can pass the word check
and still be a machine dashboard.

## 2. Calm by default; loud only when something is actually wrong

The page's centre of gravity moves. When nothing needs the operator, the companies are the hero
and the approvals region collapses to one quiet line. When something needs a decision, it takes
the top of the page and is unmistakable.

Colour is the scarcest resource in the system. On a company card, colour means **health status
and nothing else** — this is why the company-kind label is quiet grey type rather than a badge.
A second thing that uses colour on that card destroys the first thing's meaning.

**Violation looks like:** coloured category chips next to a health meter; a permanent red
element; a notification style used for a non-notification; a chart with a rainbow palette.

## 3. Real data, or an honest absence — never a plausible placeholder

Every tile, meter, trend and count is backed by an endpoint Jarvis actually serves. When a value
does not exist yet, the surface says so in its own words and, where useful, says when it will
exist ("Nothing measured yet — check back after its next work session").

**Violation looks like:** a sparkline drawn from random data because the trend endpoint is not
built; a "3 active managers" tile counting something else; a KPI panel with lorem values behind
a "demo mode" flag. M7-F53/F60 were both this defect wearing different clothes.

This principle is why the persona components in `11-persona-components.md` ship as a **spec with
no rendering path**: the data does not exist yet, so the component must not appear yet.

## 4. Progressive disclosure, three deep and no deeper

Card → Details → full history. The card carries the one number and the one sentence that answer
"should I look closer?". Details carries the breakdown. Full history carries the audit record,
and is fetched only when opened — drill-down is opt-in per §12.5, and loading it eagerly makes
it part of the default view in everything but appearance.

**Violation looks like:** a card that carries three meters and a breakdown; a fourth level; a
"Details" that is just the card again; eagerly fetching the audit payload so the network tab
tells a different story than the UI does.

## 5. Empty, null and error states are designed with the happy path, not after it

A screen with nothing in it is the best moment to teach. A failure states what happened and what
to do next, never just what broke. A missing measurement is a sentence, not a blank or a zero —
zero is a *measurement*, and rendering "not yet measured" as `0` is a lie of format.

**Violation looks like:** `—`, `N/A`, `null`, `0`, an empty card, a spinner that never resolves,
or a raw object rendered at the operator. M7-5b item 3 ("measured not measured yet") was this
principle failing at the sentence level; it is pinned by a test now.

## 6. Motion reports state change; it never performs

The one animation in the shipped surface is the breathing dot on a running company — it encodes
a fact (this company is live) that no static mark conveys as well. Everything else is a
transition that makes a change legible: something arriving, something leaving, something
becoming urgent.

**Violation looks like:** entrance animations on page load, staggered card reveals, hover
flourishes, parallax, a skeleton shimmer that outlives the request it stands for. See
`08-motion.md`.

---

## The craftsmanship bar

Premium SaaS. Concretely, and testably: consistent optical rhythm on a 4px grid; type that uses
a real scale rather than arbitrary sizes; every interactive element with a visible, high-contrast
focus state; no layout shift when data arrives; every state of every component drawn before it
ships; and contrast ratios that are *measured* (`09-accessibility.md`) rather than assumed.

## What this system deliberately does not do

It does not chase visual novelty. Jarvis is an instrument an owner looks at every day to decide
whether to trust autonomous companies with money. Instruments earn trust by being legible,
predictable and quiet. The design language is therefore closer to a trading terminal or an
aircraft panel than to a marketing site — density with air, not decoration.
