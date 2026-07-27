// The single create-company dialog (M6-5a item 2: one flow, not two).

import { get } from './api.js';
import { action } from './actions.js';
import { esc } from './format.js';
import { openSheet, sheet, closeSheet } from './panel.js';
import { refresh } from './refresh.js';

const el = (id) => document.getElementById(id);

async function openNew() {
  const templates = await get('/api/company-templates');
  if (!templates.length) {
    // An empty state that teaches: what a template is, and the one step that
    // gets past this screen.
    openSheet(`<h2 id="sheetTitle">No templates installed</h2>
      <p class="reason reason--lede">A company template describes what a company
      does. Install the starter template, then come back here to create a company from it.</p>
      <div class="acts acts--plain">
        <button class="btn btn--primary" data-act="install-templates">Install starter template</button>
        <button class="btn" data-act="close-sheet">Close</button>
      </div>`);
    return;
  }
  const opts = templates
    .map(
      (t) =>
        `<option value="${esc(t.id)}" data-budget="${esc(t.suggested_budget)}"
      data-round="${esc(t.suggested_round_limit)}">${esc(t.name)}</option>`,
    )
    .join('');
  openSheet(`
    <h2 id="sheetTitle">New company</h2>
    <div class="field field--lead">
      <label for="tpl">What should it do</label>
      <select id="tpl">${opts}</select>
      <p class="field__hint" id="tplWhat">${esc(templates[0].what_it_does)}</p>
    </div>
    <div class="field">
      <label for="nm">Call it</label>
      <input id="nm" placeholder="e.g. Weekend Reviews" autocomplete="off">
    </div>
    <div class="field">
      <label for="bg">Spending limit</label>
      <input id="bg" type="number" min="1" step="1" value="${esc(templates[0].suggested_budget)}">
      <p class="field__hint">It stops on its own at this limit. You can change it later.</p>
    </div>
    <div class="field">
      <label for="rd">Most it can spend per work session</label>
      <input id="rd" type="number" min="0.01" step="0.01"
        value="${esc(templates[0].suggested_round_limit)}">
      <p class="field__hint">A cap on one round of work, inside the spending limit above.</p>
    </div>
    <p class="formErr" id="newErr"></p>
    <div class="acts acts--plain">
      <button class="btn btn--primary" data-act="create-co">Create and start</button>
      <button class="btn" data-act="close-sheet">Cancel</button>
    </div>`);

  sheet()
    .querySelector('#tpl')
    .addEventListener('change', (ev) => {
      const opt = templates.find((t) => t.id === ev.target.value);
      el('tplWhat').textContent = opt.what_it_does;
      el('bg').value = opt.suggested_budget;
      el('rd').value = opt.suggested_round_limit;
    });
  el('nm').focus();
}

async function createCo() {
  const name = el('nm').value.trim();
  if (!name) {
    el('newErr').textContent = 'Give it a name first.';
    el('nm').focus();
    return;
  }
  const res = await fetch('/api/companies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      template: el('tpl').value,
      name,
      budget_usd: Number(el('bg').value),
      per_round_limit_usd: Number(el('rd').value) || null,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // Never render a raw object or array at the operator (§12.5) — the
    // backend always sends a plain sentence, but stay defensive.
    el('newErr').textContent =
      typeof body.detail === 'string' && body.detail
        ? body.detail
        : "Jarvis couldn't create that company. Please try again.";
    return;
  }
  closeSheet();
  refresh();
}

export function registerNewCoActions() {
  action('open-new', () => openNew());
  action('create-co', () => createCo());

  // A control that takes perceptible time disables itself and swaps its label
  // to a present participle. No spinners: a disabled control with a changed
  // label says the same thing and cannot animate forever if something fails.
  action('install-templates', async (_data, btn) => {
    btn.disabled = true;
    btn.textContent = 'Installing…';
    const res = await fetch('/api/company-templates/install-builtin', { method: 'POST' });
    if (!res.ok) {
      btn.disabled = false;
      btn.textContent = 'Install starter template';
      return;
    }
    openNew(); // reopen with templates now present
  });
}
