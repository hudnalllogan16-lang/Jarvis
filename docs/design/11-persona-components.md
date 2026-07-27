# 11 — Persona Components (SPEC ONLY)

**Status: specification. No rendering path ships in M8-2.**

Persona *data* does not exist — no endpoint serves a manager name, responsibility, or workload.
Rendering a persona now would mean inventing one, which `01-principles.md` #3 forbids and which
is precisely the defect class (M7-F53, M7-F60) this project has already paid for twice. The
visual language is settled here so the packet that plumbs the data has nothing left to invent.

All copy below is **placeholder quality and flagged for `operator-surface-engineer`**. Persona
naming in particular is a product decision this role does not hold.

---

## What a persona is, and the line it must not cross

Spec v1.5 (D-028.1, owner-authorised) changed §12.5's Business Manager row from *invisible* to
**"MAY be represented as a named operational persona"** — responsibility, ownership, current
activity, health, workload. D-007's manager row is superseded accordingly.

The persona is an **abstraction layer over ownership**, not a window into the machine. The
target experience is *"supervising a team of executives, not monitoring background processes."*

| A persona MAY surface | A persona may NEVER surface |
|---|---|
| a name | anything §12.5's forbidden list covers |
| what it is responsible for (which company) | its internal structure or composition |
| what it is doing now, in operator language | what it is built from, or how it decides |
| its company's health | its instructions, or how it is configured |
| how much it is handling (workload) | counts of internal units of work |

The forbidden column is not a styling concern — it is the §12.5 static gate, which binds this
design like everything else. **If a persona design wants to show something §12.5 forbids, the
design is wrong, not the rule.**

The sharpest trap: "workload" must be expressed in terms an owner uses about a person — how many
companies, how much is waiting — never in units of internal work. A workload meter that counts
anything the platform does internally is a monitoring dashboard wearing a name badge, and it
converts an approved abstraction back into the thing the spec forbids.

---

## The components

### Persona chip — `.persona-chip`

The compact form. Appears wherever a company's ownership is relevant: on a company card, beside
an activity entry, in an approval card's header.

**Anatomy.** monogram → name → optional status dot.

    ┌──────────────────────┐
    │ (ST)  Stella   ●     │
    └──────────────────────┘

- **Monogram**: initials, 20px circle, `--font-data`, `--text-2xs`, on `--surface-hover` with a
  `--border-subtle` ring. **Not an avatar image** — a photo of a person who does not exist is
  the least honest thing this system could render, and it would be a dependency and a network
  request besides.
- **Name**: `--font-display`, `--text-sm`, `--text-primary`.
- **Status dot**: reuses `.dot` and its band semantics — *its company's* health, not a separate
  score.

**States.** rest · hover (surface lifts; the chip is a control into the persona's detail) ·
focus-visible (standard ring) · unassigned (**no chip renders at all** — never a "—" or a
grey placeholder person).

**Rules.** The chip never carries a role title as colour, never a badge count, and never appears
without a company context. A persona detached from what it is responsible for is decoration.

### Persona header — `.persona-header`

The expanded form, for a persona's own view or the top of a company workspace.

**Anatomy.**

    (ST)  Stella
          Looks after Trailhead Gear Reviews
          ── RESPONSIBLE FOR ──────────────
          1 company · $1.45 spent today
          ── RIGHT NOW ────────────────────
          "Checking today's post against your rules."
          ── NEEDS YOU ────────────────────
          1 decision waiting

**Field mapping — every line must resolve to a real served value before this ships:**

| Line | Needs | Exists today? |
|---|---|---|
| name, monogram | a persona identity on the manager | **no** |
| "Looks after X" | company ↔ manager association | **no** (derivable) |
| responsible-for counts | company count, spend | yes (`/api/summary`, `/api/companies`) |
| "Right now" | the company's `doing` string | yes |
| "Needs you" | approvals scoped to the company | yes (`/api/approvals`) |

Two of five need new data. That is the packet that unblocks this one.

### Persona roster — `.persona-roster`

A list of personas for the shell's nav or a portfolio view. Rows of persona chip + company +
health meter + a "needs you" count.

**Empty state.** "No companies yet — when you create one, you'll meet whoever looks after it."
Teaches, per `10-interaction-patterns.md`.

**Rule.** The roster is sorted by *what needs the operator*, then by health ascending. Never
alphabetically: a roster is a triage surface, not a directory.

---

## Visual rules

1. **Personas are never louder than their company.** On a company card the company name is
   `--text-xl` display; the persona chip is `--text-sm`. The operator owns companies; personas
   are how the work inside one is attributed.
2. **A persona's colour is its company's health.** Personas get no palette of their own — a
   per-persona accent colour would spend the system's scarcest resource on identity rather than
   status, and would collide with the health semantics on the same card (`02-color.md` rule 2).
3. **No avatars, no illustrations, no emoji.** Monograms only.
4. **No anthropomorphic status prose.** "Stella is thinking about…" is charming once and
   untrustworthy thereafter. Activity is reported in the same operator language as everything
   else, from the same stored values, under D-011's rendering boundary.
5. **A persona never speaks in first person.** All narrative is platform-rendered from stored
   values, never model prose presented as a character's voice. The D-011 extension question for
   feed prose (M7-F50) is a live open decision and this rule must be revisited alongside it.

## Before this ships

- [ ] Persona identity data exists and is served (new packet, Lane A adjacent)
- [ ] Naming decided by the owner — invented names, company-derived names, or operator-chosen
- [ ] All copy above replaced by `operator-surface-engineer`
- [ ] §12.5 gate re-run against the rendered persona surface, with the workload wording checked
      specifically against the forbidden list
- [ ] Empty and unassigned states verified against real data, including a company whose persona
      is absent
