// The application shell: the nav rail, the workspace router, and the region
// lookup every painting module goes through.
//
// docs/design/12-application-shell.md is the specification. Two rules from it
// are load-bearing here:
//
//   1. A nav item is a promise that a destination exists. Every entry in
//      WORKSPACES below has a `data-ws` pane in index.html, and nothing else
//      is offered. Concepts the product wants but cannot serve yet (Managers,
//      Goals & KPIs, Activity, Audit) are RESERVED IN THE DESIGN DOCUMENT and
//      appear in no list here — a nav item leading nowhere is decorative
//      furniture that lies, which is docs/design/01-principles.md #3 applied
//      to navigation itself. Pinned by tests/test_design_system.py.
//
//      DETAIL_ROUTES is the M9-2 extension, and it does not weaken that rule.
//      A detail route is a pane reached by drilling INTO a workspace rather
//      than from the rail (`#/companies/<id>`). What the rule forbids is an
//      ORPHAN — a pane nothing reaches — so a detail route must name a parent
//      that is itself a rail workspace, and that parent's rail item stays lit
//      while the operator is inside. Both halves are pinned by the same test.
//
//   2. Only the active workspace is painted. Two panes declare a region with
//      the same name (the company grid appears on the Command Center and on
//      Companies); painting both would put two elements with the same id in
//      one document, which breaks getElementById for the approval payload
//      fields. `region()` resolves to the visible one, and navigating away
//      empties the pane being hidden so stale markup cannot linger.

import { action } from './actions.js';
import { esc } from './format.js';
import { trapFocus, focusFirst } from './focus.js';
import { sheetOpen } from './panel.js';

const el = (id) => document.getElementById(id);

/** The shipped workspaces, in rail order. `badge` names a count that needs the
 *  operator; a nav badge never shows a total (docs/design/06-components.md). */
const WORKSPACES = [
  { id: 'command-center', label: 'Command Center' },
  { id: 'companies', label: 'Companies' },
  { id: 'approvals', label: 'Approvals', badge: true },
  { id: 'settings', label: 'Settings' },
];

/** Destinations reached by drilling into a workspace, never from the rail
 *  (docs/design/12-application-shell.md, "Detail routes"). `parent` is both
 *  the hash segment that addresses them (`#/<parent>/<id>`) and the rail item
 *  that stays lit while the operator is inside one. */
const DETAIL_ROUTES = [{ id: 'company', parent: 'companies' }];

const DEFAULT_WS = WORKSPACES[0].id;

/** A resolved route: which pane is showing, and — for a detail route — whose
 *  rail item stays lit and which record is being shown. */
let current = { ws: DEFAULT_WS, parent: null, id: null };
let onRoute = () => {};
let releaseRail = null;

/** The named region inside the ACTIVE workspace, or null when the active
 *  workspace has no such region. A painting module that gets null skips its
 *  work for this cycle — it is not an error, it means the operator is looking
 *  at something else. */
export function region(name) {
  for (const node of document.querySelectorAll(`[data-region="${name}"]`)) {
    const pane = node.closest('[data-ws]');
    if (!pane || !pane.hidden) return node;
  }
  return null;
}

/** Set a nav item's count pill. Zero removes it: a badge reading 0 is chrome
 *  reporting that nothing needs the operator, which is what the calm surface
 *  already says better. */
export function navCount(id, count) {
  const slot = document.querySelector(`[data-nav="${id}"] [data-count]`);
  if (!slot) return;
  slot.textContent = count ? String(count) : '';
  slot.hidden = !count;
}

/** The active route. A painting module reads `id` to know WHICH record it is
 *  looking at; `ws` and `parent` are the shell's own business. */
export function currentRoute() {
  return current;
}

/** The only part of the frame a workspace module may write to, and only
 *  because a detail route's title is DATA rather than a label the shell holds
 *  (docs/design/12-application-shell.md). Everything else in the top bar, the
 *  rail and the system strip is painted from the platform's own endpoints: a
 *  workspace that could rewrite the health banner could make a broken
 *  platform look fine. */
export function setWorkspaceTitle(text) {
  el('wsTitle').textContent = text;
}

function railIsOverlay() {
  return !!el('railToggle').offsetParent;
}

function closeRail() {
  document.body.classList.remove('rail-open');
  el('railToggle').setAttribute('aria-expanded', 'false');
  if (releaseRail) {
    const release = releaseRail;
    releaseRail = null;
    release();
  }
}

function openRail() {
  document.body.classList.add('rail-open');
  el('railToggle').setAttribute('aria-expanded', 'true');
  releaseRail = trapFocus(el('rail'), el('railToggle'));
  focusFirst(el('rail'));
}

function railOpen() {
  return document.body.classList.contains('rail-open');
}

function renderNav() {
  el('nav').innerHTML = WORKSPACES.map(
    (w) => `<a class="nav-item" href="#/${esc(w.id)}" data-nav="${esc(w.id)}">
      <span class="nav-item__label">${esc(w.label)}</span>${
        w.badge ? '<span class="nav-item__count" data-count hidden></span>' : ''
      }</a>`,
  ).join('');
}

/** Show one pane and empty the one leaving, so no two panes ever hold the same
 *  region's markup at once. Panes are read from the document rather than from
 *  WORKSPACES: detail panes are panes too, and the rail↔pane test is what
 *  keeps the two lists honest about each other. */
function show(r) {
  for (const pane of document.querySelectorAll('[data-ws]')) {
    const active = pane.dataset.ws === r.ws;
    // Also cleared when the pane stays but the RECORD changes: drilling from
    // one company straight to another would otherwise leave the first one's
    // numbers on screen under the second one's name until the fetch returns.
    const stale = !active || r.id !== current.id;
    if (stale && !pane.hidden) {
      for (const slot of pane.querySelectorAll('[data-region]')) slot.innerHTML = '';
    }
    pane.hidden = !active;
  }

  // Inside a detail route the PARENT's rail item stays lit: a rail with
  // nothing lit tells an operator they are nowhere.
  const lit = r.parent || r.ws;
  for (const w of WORKSPACES) {
    const link = document.querySelector(`[data-nav="${w.id}"]`);
    if (!link) continue;
    const active = w.id === lit;
    link.classList.toggle('nav-item--on', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }

  // A detail route's own title is data and arrives with its fetch; the parent
  // label holds the slot until the pane's module replaces it, so the title is
  // never blank and never a raw identifier.
  const named = WORKSPACES.find((w) => w.id === lit);
  if (named) setWorkspaceTitle(named.label);
  current = r;
}

function routeFromHash() {
  const want = (location.hash || '').replace(/^#\//, '');
  const cut = want.indexOf('/');
  if (cut > 0) {
    const parent = want.slice(0, cut);
    const id = decodeURIComponent(want.slice(cut + 1));
    const detail = DETAIL_ROUTES.find((d) => d.parent === parent);
    if (detail && id) return { ws: detail.id, parent, id };
  }
  // A detail route can never be reached by fallback — the fallback has no id
  // to supply — so an unrecognised hash lands on the Command Center as before.
  return {
    ws: WORKSPACES.some((w) => w.id === want) ? want : DEFAULT_WS,
    parent: null,
    id: null,
  };
}

function route() {
  const r = routeFromHash();
  const changed = r.ws !== current.ws || r.id !== current.id;
  show(r);
  if (railIsOverlay() && railOpen()) closeRail();
  // The workspace is what changed, so move the reading position to it — but
  // only on a real navigation, never on the initial paint, where stealing
  // focus would fight the operator's own first Tab. Drilling from one company
  // to another counts as a navigation even though the pane never changed,
  // which is why `id` is part of the comparison.
  if (changed) el('ws').focus();
  onRoute(r);
}

export function startShell(repaint) {
  onRoute = repaint;
  renderNav();

  action('toggle-rail', () => (railOpen() ? closeRail() : openRail()));

  el('railScrim').addEventListener('click', () => {
    if (railOpen()) closeRail();
  });

  // The sheet sits above the rail, so it answers Escape first: one press must
  // never dismiss both overlays. Ordering by an explicit check rather than by
  // listener registration order, which is a composition-root detail no module
  // should depend on.
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && railOpen() && !sheetOpen()) closeRail();
  });

  // A docked rail must not keep the overlay's body class, or the scrim stays
  // clickable over a rail that is no longer covering anything.
  window.addEventListener('resize', () => {
    if (!railIsOverlay() && railOpen()) closeRail();
  });

  window.addEventListener('hashchange', route);
  show(routeFromHash());
}
