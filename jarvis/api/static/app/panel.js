// The modal sheet — the surface's only overlay.
//
// Known gap (finding M8-F23): focus is not trapped inside the open sheet and
// is not restored to the invoking control on close. Recorded in
// docs/design/09-accessibility.md rather than half-fixed here; it belongs with
// the Application Shell's focus management (M8-4), which owns chrome.

const el = (id) => document.getElementById(id);

/** Replace the sheet's contents and open it. */
export function openSheet(html) {
  el('sheet').innerHTML = html;
  el('panel').classList.add('panel--open');
}

/** The sheet element, for callers that need to bind to what they just wrote. */
export const sheet = () => el('sheet');

export function closeSheet() {
  el('panel').classList.remove('panel--open');
}

/** Dismissal paths: the scrim, Escape, and the sheet's own Close button
 *  (which routes through the `close-sheet` action). */
export function startPanel() {
  el('panel').addEventListener('click', (ev) => {
    if (ev.target.id === 'panel') closeSheet();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeSheet();
  });
}
