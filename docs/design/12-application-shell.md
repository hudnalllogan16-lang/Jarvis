# 12 — The Application Shell

The permanent frame every later UI phase inherits (M8-4). `05-layout.md` reserved its slots;
this document fills them and states the rules that bind what may be added to it.

    ┌────────────┬───────────────────────────────────────────────┐
    │            │  top bar    status · workspace · New company   │
    │  rail      ├───────────────────────────────────────────────┤
    │            │  system strip  health · flash · notifications  │
    │  wordmark  ├───────────────────────────────────────────────┤
    │  nav       │                                               │
    │            │  workspace                                    │
    │            │                                               │
    └────────────┴───────────────────────────────────────────────┘

**Only the workspace changes when the operator navigates.** The rail, the top bar and the
system strip are furniture: they answer "where am I, is Jarvis working, what needs me" from
every route, and an operator who has learned where those answers live never has to learn again.
This is the whole argument for a shell over a page.

---

## The rule that decides what appears in the rail

> **A nav item is a promise that a destination exists.**

A rail entry leading to an empty screen, a "coming soon", or a view assembled from data Jarvis
does not serve is decorative furniture that lies — `01-principles.md` #3 applied to navigation
itself. So the rail lists exactly the workspaces that are built, and concepts that are not yet
buildable are **reserved in this document**, where a reservation costs the operator nothing.

`tests/test_design_system.py` pins this mechanically: every rail item resolves to a `data-ws`
pane in `index.html`, and every pane is reachable — from the rail, or from the workspace that
owns it (see "Detail routes" below). Neither side can grow without the other.

### Shipped workspaces

| Workspace | Carries | Backed by |
|---|---|---|
| **Command Center** | stat row, attention (approvals), companies grid | `/api/summary`, `/api/approvals`, `/api/companies` |
| **Companies** | the roster, full width, nothing competing | `/api/companies` |
| **Approvals** | the decision queue as *work* rather than as an interruption | `/api/approvals` |
| **Settings** | what Jarvis can run; parts of the app | `/api/settings/subsystems`, `/api/health` |

Command Center and Approvals both render the approvals region, and Command Center and Companies
both render the company grid. They are the same component in two framings: on the Command Center
approvals are **attention** — loud when pending, one calm line when not (`01-principles.md` #2)
— and on their own workspace they are a queue the operator went looking for.

### Reserved — specified, deliberately not built

| Concept | Why it does not ship | What would unblock it |
|---|---|---|
| **Managers** | No persona data exists. A persona invented to fill a chip is the defect `11-persona-components.md` was written to prevent. | An endpoint serving manager personas (spec v1.5, D-028.1) |
| **Goals & KPIs** | Goals are served only inside `/api/companies/{id}` — a level-2 drill-down. A cross-company view would need N per-company fetches, pulling activity, stuck work and grants to display none of them. | A cross-company goals read endpoint |
| **Activity** | Same shape: the Decision Log is per company. The Command Center's activity feed is reserved for the same reason. | A cross-company activity read endpoint |
| **Audit** | Both of the above **and** an information-architecture conflict: the audit record is level 3 in `10-interaction-patterns.md`. A top-level Audit workspace makes it level 1 and inverts a ladder that document calls "exactly three levels". | A read endpoint **and** a decision about the ladder |

The last row is the one to re-read before adding it. The other three are missing data; that one
is a missing *decision*, and it belongs to the Manager, not to a UI packet.

### Detail routes — destinations the rail does not own

Added at M9-2 for the company workspace (`13-company-workspace.md`). A **detail route** is a pane
the operator reaches by drilling into a workspace rather than by clicking the rail:

    #/companies            a rail workspace
    #/companies/<id>       its detail route — one company

The rail rule is unchanged in force, only in phrasing. "A nav item is a promise that a destination
exists" was always about *nav items*; it never said every destination must be a nav item. What
would be wrong is an **orphan** — a pane nothing reaches — and that is still forbidden, which is
why a detail route declares its parent rather than merely existing:

    <section class="ws__pane" data-ws="company" data-ws-parent="companies" hidden>

Three rules follow, and each exists because the naive version gets it wrong:

- **The parent's rail item stays lit.** Inside a company, `Companies` keeps `nav-item--on` and
  `aria-current="page"`. A rail with nothing lit tells an operator they are nowhere; lighting a
  fifth item that is not in the rail is not available.
- **The parent must be a real workspace.** A detail route whose parent is not in the rail is an
  orphan one level removed — reachable only by typing a URL. Pinned by test.
- **A detail route is never the default.** An unrecognised hash falls back to the Command Center,
  as before; a route needing an id can never be reached by fallback, because the fallback has no
  id to supply.

### The top bar title on a detail route

A workspace's title is its label — a constant the shell already holds. A detail route's title is
**data**, and data arrives after the paint. So the shell sets the parent's label on navigation and
exposes one setter (`setWorkspaceTitle`) for the pane's own module to replace it once the fetch
lands. The title is therefore never empty and never a raw identifier; at worst it reads
`Companies` for one frame before it reads `Portfolio Watch`.

This is the only thing in the frame a workspace module may write to. Everything else in the top
bar, the rail and the system strip is platform-level and is painted from the platform's own
endpoints — a workspace that could rewrite the health banner could make a broken platform look
fine.

---

## The regions contract

Painting is scoped to the **active** workspace. `app/shell.js` exposes `region(name)`, which
resolves a logical region to the container inside the visible pane, or `null` when no visible
pane declares it — and a module that gets `null` does nothing that cycle.

Two panes may declare the same region name. Only one is ever filled, and navigating away empties
the pane being hidden. This is not tidiness: the approval payload's fields carry ids
(`f-<approval>-<key>`, `out-<approval>`) that `getElementById` resolves when corrections are
collected. Two populated copies would mean two elements with one id, and the operator's edits
would be read from whichever the browser returned first.

**Rule:** a region is filled in at most one place at a time. A new workspace that wants an
existing region declares the same `data-region` name and inherits this behaviour; it never
clones the markup.

## Navigation

Hash routes (`#/companies`), because the dependency-light constraint stands — no build step, no
router, and a hash route survives a reload and can be linked. Rail items are `<a href>`: they
navigate, so they are links, and they get keyboard activation for free
(`09-accessibility.md`). The active item carries `aria-current="page"` **and** an accent left
rule **and** primary-weight text; colour never carries it alone.

**The rule generalises to every control that navigates**, which is what M9-2's detail route made
concrete: "Details" on a company card, "more in Details" in a truncated update, and "Why?" on an
approval all change the route, so all three are `<a href="#/companies/<id>">` wearing `.btn` or
`.btn--link`. They were buttons behind a JS handler until the destination became a route, and
that shape cost the operator middle-click, open-in-new-tab, the browser's own Back, and the
status-bar preview of where they were about to go. A control that navigates is a link; a control
that acts is a button. `[data-act]` is for the second kind only.

On navigation, focus moves to the workspace (`<main tabindex="-1">`) so a keyboard operator
continues from the content that just changed rather than from the top of the document. The
initial paint does **not** move focus — stealing it before the operator has acted would fight
their first Tab.

### The nav badge

One count, on Approvals, and only ever a count that **needs the operator**. A badge showing a
total ("12 companies") trains the operator to ignore badges, which costs the one badge that
means something. Zero removes the badge rather than rendering `0` — the calm surface already
says nothing is waiting, and better.

## Responsive behaviour

| Width | Rail |
|---|---|
| ≥ `--bp-shell` (1180px) | docked, `grid-template-columns: var(--layout-rail) 1fr` |
| < `--bp-shell` | overlay: fixed, slid off-screen, revealed by the top bar's Menu control |

`--bp-shell` is 1180 rather than `--bp-lg` because the docked rail needs its own 216px *plus*
the 1080px workspace measure; below that the workspace takes the full viewport instead of
surrendering a third of it to furniture.

The closed overlay rail is `visibility: hidden`, not merely translated. A transformed element is
still focusable, so transform alone would leave a keyboard operator tabbing through four
invisible off-screen links before reaching the control that reveals them (finding M8-F80).

## Focus and the two overlays

The sheet and the overlay rail have identical obligations, so they share one implementation
(`app/focus.js`): contain Tab while open, return focus to the invoking control on close. This
closes **M8-F23**.

Two cases the naive version gets wrong, both found by live verification rather than by reading:

- **The invoker no longer exists.** The surface repaints every 15 seconds; a panel left open
  across a cycle outlives the button that opened it. Focus falls back to the workspace rather
  than being dropped on `<body>`, where a keyboard operator would restart from the document top.
- **There was no invoker.** `document.activeElement` is `<body>` when nothing holds focus.
  Restoring focus *to* `<body>` is a silent no-op — the failure that looks exactly like success
  (finding M8-F79).

Escape is answered by the sheet first when both are open, decided by an explicit check rather
than by listener registration order, which is a composition-root detail no module should depend
on.

## What the shell does not do

- **No time-range control.** The concept image has one; Jarvis serves no time series, so it
  would be a control that changes nothing. Dropped, not faked (`01-principles.md` #3).
- **No search.** Nothing to search across yet.
- **No collapse-to-icons rail.** `07-iconography.md` — the labels *are* the navigation, and an
  icon rail would require inventing a glyph per workspace to save 216px on screens that have it.
