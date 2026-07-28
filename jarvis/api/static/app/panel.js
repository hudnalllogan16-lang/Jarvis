// The modal sheet — the surface's only overlay above the workspace.
//
// Finding M8-F23 is closed here: focus is contained while the sheet is open
// and returned to the invoking control when it closes (WCAG 2.4.3). The
// containment itself lives in focus.js, which the rail overlay also uses —
// the two overlays have identical obligations and solving it twice is how
// they drift apart.

import { action } from './actions.js';
import { trapFocus, focusFirst } from './focus.js';

const el = (id) => document.getElementById(id);

/** Non-null exactly while the sheet is open. Also the "already open" flag:
 *  several flows re-render an open sheet in place (revoking a grant reopens
 *  Details, toggling a subsystem reopens Settings, installing templates
 *  reopens New company), and trapping again on each would stack listeners and
 *  overwrite the remembered invoker with a button inside the sheet. */
let release = null;

/** Replace the sheet's contents and open it. */
export function openSheet(html) {
  el('sheet').innerHTML = html;
  const first = !release;
  el('panel').classList.add('panel--open');
  if (first) release = trapFocus(el('sheet'), el('ws'));
  focusFirst(el('sheet'));
}

/** The sheet element, for callers that need to bind to what they just wrote. */
export const sheet = () => el('sheet');

export function closeSheet() {
  if (!el('panel').classList.contains('panel--open')) return;
  el('panel').classList.remove('panel--open');
  const done = release;
  release = null;
  if (done) done();
}

export function sheetOpen() {
  return !!release;
}

/** Dismissal paths: the scrim, Escape, and the sheet's own Close button.
 *
 *  `close-sheet` is registered here since M9-2. It used to live in
 *  companies.js because the Details sheet was that module's, but level 2 is a
 *  route now and the create-company dialog is the sheet's only remaining
 *  content — leaving the dismissal of the overlay registered by a module that
 *  no longer opens it is how an action outlives its owner. The overlay
 *  registers its own. */
export function startPanel() {
  action('close-sheet', () => closeSheet());

  el('panel').addEventListener('click', (ev) => {
    if (ev.target.id === 'panel') closeSheet();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeSheet();
  });
}
