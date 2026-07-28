// Transient messages for actions that have no dialog of their own.
//
// Shown when an action fails outside a dialog that already has its own error
// slot (approve/deny, pause/start, from anywhere in the page) — a plain
// sentence, never a silently swallowed non-2xx response.
//
// `tone` (M9-9 product REVISE item 3) extends this to a plain one-line
// acknowledgment for an action whose success leaves no other visible trace —
// consenting to a pending template update, unlike Pause/Start's own visible
// flip, disappears from the page with nothing to say it worked. `'note'`
// reuses the accent-toned, non-alarming banner the notification center
// already renders informational text in (`system.js`'s `paintNotes`): a
// stated result, never `'down'`'s risk-red, and never a congratulation —
// see `components.css`'s own `.banner` rule for why "never a congratulation"
// still holds.
import { esc } from './format.js';

let timer;

export function flash(message, tone = 'down') {
  const region = document.getElementById('flash');
  region.innerHTML = `<div class="banner banner--${tone}">${esc(message)}</div>`;
  clearTimeout(timer);
  timer = setTimeout(() => {
    region.innerHTML = '';
  }, 6000);
}
