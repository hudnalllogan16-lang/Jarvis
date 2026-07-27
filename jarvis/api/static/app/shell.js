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

const DEFAULT_WS = WORKSPACES[0].id;

let current = DEFAULT_WS;
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

function paneOf(id) {
  return document.querySelector(`[data-ws="${id}"]`);
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

/** Show one workspace and empty the one leaving, so no two panes ever hold the
 *  same region's markup at once. */
function show(id) {
  for (const w of WORKSPACES) {
    const pane = paneOf(w.id);
    if (!pane) continue;
    const active = w.id === id;
    if (!active && !pane.hidden) {
      for (const slot of pane.querySelectorAll('[data-region]')) slot.innerHTML = '';
    }
    pane.hidden = !active;
    const link = document.querySelector(`[data-nav="${w.id}"]`);
    if (link) {
      link.classList.toggle('nav-item--on', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
    if (active) el('wsTitle').textContent = w.label;
  }
  current = id;
}

function routeFromHash() {
  const want = (location.hash || '').replace(/^#\//, '');
  return WORKSPACES.some((w) => w.id === want) ? want : DEFAULT_WS;
}

function route() {
  const id = routeFromHash();
  const changed = id !== current;
  show(id);
  if (railIsOverlay() && railOpen()) closeRail();
  // The workspace is what changed, so move the reading position to it — but
  // only on a real navigation, never on the initial paint, where stealing
  // focus would fight the operator's own first Tab.
  if (changed) el('ws').focus();
  onRoute(id);
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
