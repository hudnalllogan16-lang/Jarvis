// Platform status: the health banner, notifications, and the Settings sheet.

import { get, post } from './api.js';
import { action } from './actions.js';
import { esc, ago, plural } from './format.js';
import { openSheet, closeSheet } from './panel.js';

const el = (id) => document.getElementById(id);

/** Degraded dependencies, with the remedy that fixes them. Silent when every
 *  component is healthy — a banner is never used to report success. */
export async function paintHealth() {
  try {
    const h = await get('/api/health');
    const bad = h.components.filter((c) => c.status !== 'ok');
    el('healthbar').innerHTML = bad.length
      ? bad
          .map(
            (c) =>
              `<div class="banner ${c.status === 'down' ? 'banner--down' : ''}">
          <b>${esc(c.summary)}</b>${c.remedy ? ' ' + esc(c.remedy) : ''}</div>`,
          )
          .join('')
      : '';
  } catch (e) {
    el('healthbar').innerHTML =
      `<div class="banner banner--down"><b>Jarvis isn't responding.</b> Is it still running?</div>`;
  }
}

export async function paintNotes() {
  const notes = await get('/api/notifications');
  el('notes').innerHTML = notes
    .slice(0, 5)
    .map(
      (n) =>
        `<div class="banner banner--note"><span><b>${esc(n.title)}</b> — ${esc(n.body)}</span>
     <button class="btn btn--small" data-act="dismiss-note"
       data-id="${esc(n.id)}">Dismiss</button>
     <time datetime="${esc(n.when)}">${esc(ago(n.when))}</time></div>`,
    )
    .join('');
}

async function openSettings() {
  const subs = await get('/api/settings/subsystems');
  const parts = (await get('/api/health').catch(() => ({ parts: [] }))).parts || [];
  openSheet(`
    <h2 id="sheetTitle">Settings</h2>
    <h3 class="section-head">What Jarvis can run</h3>
    <p class="reason" style="margin:0 0 10px">Turning something off hides it from
      "New company". Companies you already have keep their own pause switch.</p>
    ${
      subs
        .map(
          (t) => `<div class="entry"><p><b>${esc(t.name)}</b>
        <span class="why">${esc(t.companies)} ${plural(
          t.companies,
          'company',
          'companies',
        )}</span>
        <button class="btn btn--small" style="float:right" data-act="toggle-sub"
          data-id="${esc(t.id)}" data-enabled="${t.enabled ? 'no' : 'yes'}">
          ${t.enabled ? 'Turn off' : 'Turn on'}</button></p></div>`,
        )
        .join('') || '<p class="calm">Nothing installed yet.</p>'
    }
    <h3 class="section-head">Parts of the app</h3>
    ${parts
      .map(
        (p) => `<div class="entry"><p>${esc(p.name)}
        <span class="why">${
          p.state === 'running'
            ? 'running'
            : p.state === 'restarting'
              ? 'restarting itself'
              : esc(p.state)
        }</span></p></div>`,
      )
      .join('')}
    <div class="acts" style="border:0;margin-top:14px">
      <button class="btn" data-act="close-sheet">Close</button></div>`);
}

export function registerSystemActions() {
  action('open-settings', () => openSettings());

  action('dismiss-note', async ({ id }) => {
    await post(`/api/notifications/${id}/dismiss`);
    paintNotes();
  });

  action('toggle-sub', async ({ id, enabled }) => {
    await post(`/api/settings/subsystems/${id}`, { enabled: enabled === 'yes' });
    openSettings();
  });
}

export { closeSheet };
