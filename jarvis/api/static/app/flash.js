// Transient failure messages for actions that have no dialog of their own.
//
// Shown when an action fails outside a dialog that already has its own error
// slot (approve/deny, pause/start, from anywhere in the page) — a plain
// sentence, never a silently swallowed non-2xx response.

import { esc } from './format.js';

let timer;

export function flash(message) {
  const region = document.getElementById('flash');
  region.innerHTML = `<div class="banner banner--down">${esc(message)}</div>`;
  clearTimeout(timer);
  timer = setTimeout(() => {
    region.innerHTML = '';
  }, 6000);
}
