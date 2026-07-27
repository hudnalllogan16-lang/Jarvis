// Platform status: the health banner, the top bar's status word, the
// notification center, and the Settings workspace.
//
// Health, flash and notifications belong to the FRAME, not to a workspace:
// they report on the platform rather than on whatever the operator is looking
// at, so they render once, above the workspace, on every route
// (docs/design/05-layout.md, "the system strip").

import { get, post } from './api.js';
import { action } from './actions.js';
import { esc, ago, plural } from './format.js';
import { region } from './shell.js';

const el = (id) => document.getElementById(id);

/** Degraded dependencies, with the remedy that fixes them. Silent when every
 *  component is healthy — a banner is never used to report success. The top
 *  bar's status word is set from the same fetch, so the two can never
 *  disagree about whether anything is wrong. */
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
    setStatus(
      bad.length ? `${bad.length} ${plural(bad.length, 'thing', 'things')} to look at` : 'All good',
      bad.length ? 'bad' : 'ok',
    );
  } catch (e) {
    el('healthbar').innerHTML =
      `<div class="banner banner--down"><b>Jarvis isn't responding.</b> Is it still running?</div>`;
    setStatus('Not responding', 'bad');
  }
}

/** One word in the top bar, always present, paired with the banner below it —
 *  colour is never the only channel (docs/design/09-accessibility.md). */
function setStatus(text, tone) {
  const slot = el('status');
  slot.textContent = text;
  slot.classList.toggle('topbar__status--bad', tone === 'bad');
}

/** The notification center. Notifications used to stack as open banners above
 *  the page, pushing the operator's work down the screen for something that is
 *  read once. They now live behind a top-bar control whose count is always
 *  visible, so nothing is hidden — the existence of an update is on screen at
 *  all times, and one click shows it. */
export async function paintNotes() {
  const notes = await get('/api/notifications');
  const shown = notes.slice(0, 5);
  el('notesToggle').innerHTML =
    `Updates${notes.length ? ` <span class="section-head__count">${notes.length}</span>` : ''}`;
  el('noteCenter').innerHTML = shown.length
    ? shown
        .map(
          (n) =>
            `<div class="banner banner--note"><span><b>${esc(n.title)}</b> — ${esc(n.body)}</span>
     <button class="btn btn--small" data-act="dismiss-note"
       data-id="${esc(n.id)}">Dismiss</button>
     <time datetime="${esc(n.when)}">${esc(ago(n.when))}</time></div>`,
        )
        .join('')
    : '<p class="calm">Nothing new. Jarvis leaves a note here for things worth knowing about but not worth deciding.</p>';
}

/** Settings is a workspace, not a dialog: it is a place the operator goes,
 *  not an interruption of what they were doing. Painted only when it is the
 *  active workspace, so its two fetches cost nothing on every other route. */
export async function paintSettings() {
  const slot = region('settings');
  if (!slot) return;
  const subs = await get('/api/settings/subsystems');
  const parts = (await get('/api/health').catch(() => ({ parts: [] }))).parts || [];
  slot.innerHTML = `
    <h2 class="section-head">What Jarvis can run</h2>
    <p class="reason reason--lede">Turning something off hides it from
      "New company". Companies you already have keep their own pause switch.</p>
    ${
      subs
        .map(
          (t) => `<div class="entry"><div class="entry__row"><b>${esc(t.name)}</b>
        <span class="entry__why">${esc(t.companies)} ${plural(
          t.companies,
          'company',
          'companies',
        )}</span>
        <button class="btn btn--small entry__act" data-act="toggle-sub"
          data-id="${esc(t.id)}" data-enabled="${t.enabled ? 'no' : 'yes'}">
          ${t.enabled ? 'Turn off' : 'Turn on'}</button></div></div>`,
        )
        .join('') ||
      '<p class="calm">Nothing installed yet — company templates you install will show up ' +
        'here, with a switch to turn each one on or off.</p>'
    }
    <h2 class="section-head">Parts of the app</h2>
    ${
      parts
        .map(
          (p) => `<div class="entry"><div class="entry__row"><span>${esc(p.name)}</span>
        <span class="entry__why">${
          p.state === 'running'
            ? 'running'
            : p.state === 'restarting'
              ? 'restarting itself'
              : esc(p.state)
        }</span></div></div>`,
        )
        .join('') ||
      '<p class="calm">Nothing to report — everything Jarvis does is running together, ' +
        'as one, right now.</p>'
    }`;
}

export function registerSystemActions() {
  action('toggle-notes', (_data, btn) => {
    const open = el('noteCenter').hidden;
    el('noteCenter').hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  action('dismiss-note', async ({ id }) => {
    await post(`/api/notifications/${id}/dismiss`);
    paintNotes();
  });

  action('toggle-sub', async ({ id, enabled }) => {
    await post(`/api/settings/subsystems/${id}`, { enabled: enabled === 'yes' });
    paintSettings();
  });
}
