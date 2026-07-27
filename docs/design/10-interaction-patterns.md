# 10 — Interaction Patterns

## Progressive disclosure: card → details → history

Exactly three levels. A fourth means the information architecture is wrong.

| Level | Surface | Carries | Costs the operator |
|---|---|---|---|
| 1 | Company card | one meter, one number, one sentence, spend, latest update | a glance |
| 2 | Details panel | health parts, goals measured-vs-target, activity feed, autonomy grants, stuck work | one click |
| 3 | Full details | the raw audit record | one more click, **and a fetch** |

**Level 1 answers "should I look closer?"** It is deliberately not a summary of level 2 — a
condensed version of everything is harder to read than one well-chosen fact. The card carries
the health *score* and the health *reason*; the three component parts that produce that score
live at level 2. This was ratified at M7-5a and is worth re-deciding never.

**Level 3 is fetched only when opened.** Drill-down is opt-in per §12.5; loading the audit
payload eagerly makes it part of the default view in everything but appearance, and the network
tab would tell a different story than the UI. The disclosure sets `data-loaded` on first open so
re-opening does not refetch.

### The truncation rule

When level-1 text is cut, it ends in an ellipsis **and** carries an explicit affordance into
level 2 ("more in Details"). Truncation without a signal is information the operator does not
know they are missing — M7 product re-review F3.

### The exception: the approval payload

The payload on an approval card is shown **open, in full, and never trimmed** — it is not a
drill-down, it is the thing being authorised. An operator who approves a summary of the words
has not approved the words (§8). This is the one place where "show everything by default" beats
progressive disclosure, and the reason is that the operator's click is a legal act.

---

## Honest empty, null and error states

Three different absences, three different treatments. Collapsing them is the most common way an
interface lies.

### Empty — the container exists, nothing is in it yet

Teach. Name what will appear, say what it will do, offer the first step.

> **No companies yet**
> Use **New company** up top to create your first one — it starts running straight away, and
> asks before doing anything that spends money.
> `[New company]`

Never "No data", never a bare dash, never an illustration in place of an explanation.

The calm variant is for a *good* emptiness — "Nothing needs you right now." An empty approvals
queue is success, and it must not look like a failed load.

### Null — the value does not exist yet

The distinction that matters: **zero is a measurement; unmeasured is not.** Rendering "not yet
measured" as `0` is a lie of format, and on a health meter it is a lie that says "at risk".

- A single unmeasured goal: "Not measured yet."
- **Every** goal unmeasured: one sentence for the whole section — "Nothing measured yet — check
  back after its next work session." Not a list of per-target stutters (M7-5b item 3, pinned by
  test).
- A metric with no reading: a sentence beside an empty meter, never a zero-filled meter.

Where a null resolves on a knowable schedule, say when. "Check back after its next work session"
is a better null state than "—" by exactly the amount of anxiety it removes.

### Error — something was attempted and failed

Every error states **what happened** and **what to do next**. Never a status code, never a raw
object, never a silently swallowed non-2xx.

| Where it failed | Where the message goes |
|---|---|
| Inside a dialog with its own error slot | `.formErr`, above the buttons, before the operator can retry |
| An action anywhere else (approve, pause) | the flash banner, auto-dismissing after 6s |
| A platform dependency | the health banner, with its remedy, persisting until fixed |

The backend always sends a plain sentence, but the surface stays defensive: if `detail` is not a
string, a generic operator-readable sentence is used rather than `[object Object]`. §12.5 forbids
rendering a raw structure at the operator, and "the backend promised" is not a defence.

Errors are never red-and-loud for a *choice*. "Say no" on an approval is a safe, legitimate
answer and is styled as one.

---

## Live update without destroying work

The surface repaints every 15 seconds. Two rules make that safe:

1. **Never replace a region the operator is editing.** If any approval payload field differs
   from its original value, or holds focus, the approvals region is skipped for that cycle. A
   repaint that deletes half-typed text in a request someone is about to authorise is a defect,
   not a refresh.
2. **Never move what the operator is about to click.** Repaints replace content in place;
   layout does not reflow, values do not animate, and nothing enters above an existing control.

## Destructive and irreversible actions

- **Approve** is the only action in the surface that spends money. It is a primary button, it
  sits beside its full payload, and it is never the default focus.
- **Correcting a payload has a stated consequence** — "If you change it, Jarvis keeps asking you
  about this one" (D-010). A consequence an operator discovers afterwards is a trap.
- Only genuinely changed fields are sent as corrections. An unchanged field echoed back would
  count against the company's autonomy streak for nothing.
- **Pause/Start** and **Undo** (revoking an autonomy grant) are reversible, so they are not
  confirmed. Confirmation dialogs on reversible actions train operators to dismiss dialogs.

## Command and dispatch

All click handling goes through one delegated listener on `[data-act]` (`app/actions.js`).
Handlers are registered by name; markup carries `data-act` plus its parameters as data
attributes.

This is a design-system rule, not just an implementation detail:

- No inline `onclick`, so no function needs to be a global, so ES modules work without a
  `window.*` namespace.
- Handlers cannot be attached to non-controls, which keeps `<div onclick>` structurally
  impossible.
- Re-rendered markup needs no re-binding — the listener is on `document` and survives every
  repaint. This is what makes the 15-second cycle cheap.

## Loading

Actions that take perceptible time disable their control and swap the label to a present-
participle sentence ("Installing…"). There are no spinners in the system: a disabled control
with a changed label says the same thing, cannot be orphaned by a failed request, and does not
animate forever if something goes wrong.
