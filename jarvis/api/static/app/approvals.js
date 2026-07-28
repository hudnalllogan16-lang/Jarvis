// The approval card — the loud object, and the surface's highest-value
// injection target. Every value on this card is escaped before it becomes
// markup (see format.js).

import { post } from './api.js';
import { action } from './actions.js';
import { companyHref } from './companies.js';
import { esc, ago } from './format.js';
import { flash } from './flash.js';
import { refresh } from './refresh.js';

export function askCard(a) {
  const facts = Object.entries(a.detail)
    .map(([k, v]) => `<div class="ask__fact"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
    .join('');
  return `<article class="ask">
    <h2>${esc(a.ask)}</h2>
    <dl class="ask__facts">${facts}</dl>
    ${outgoing(a)}
    <div class="acts">
      <button class="btn btn--primary" data-act="decide" data-id="${esc(a.id)}"
        data-verb="approve">Approve</button>
      <button class="btn" data-act="decide" data-id="${esc(a.id)}"
        data-verb="deny">Say no</button>
      <a class="btn btn--small" href="${companyHref(a.company_id)}">Why?</a>
      <span class="ask__waited">waiting ${esc(ago(a.waiting_since))}</span>
    </div></article>`;
}

/**
 * The whole attention region: the heading that gets loud, and the queue.
 *
 * The page's centre of gravity moves. When something needs the operator it
 * takes the top and is loud; when nothing does it collapses to one quiet line
 * and whatever is below becomes the hero (docs/design/01-principles.md #2).
 *
 * @param list  the approvals to show — the full queue on the Command Center
 *              and the Approvals workspace, one company's own on its
 *              workspace, where the queue is already filtered by the caller.
 * @param scope the company name when this region is scoped to one, so an
 *              empty queue says whose. "Nothing needs you right now." on a
 *              company page would be a claim about the whole platform made
 *              from inside one company — true today by accident, and a lie the
 *              moment a different company is waiting.
 */
export function asksRegion(list, scope) {
  if (list.length) {
    return (
      `<h2 class="section-head section-head--urgent">Needs your OK
         <span class="section-head__count">${list.length}</span></h2>` +
      list.map(askCard).join('')
    );
  }
  return (
    `<h2 class="section-head">Needs your OK</h2>` +
    (scope
      ? `<p class="calm">Nothing from ${esc(scope)} needs you right now.</p>`
      : `<p class="calm">Nothing needs you right now.</p>`)
  );
}

// What the yes actually authorises. Shown open, in full, and never trimmed: an
// operator who approves a summary of the words has not approved the words.
function outgoing(a) {
  const fields = a.payload || [];
  if (!fields.length) return '';
  const editable = !!a.payload_correctable;
  const rows = fields
    .map((f) => {
      const at = `${esc(a.id)}-${esc(f.key)}`;
      const control = !editable
        ? `<pre>${esc(f.value)}</pre>`
        : String(f.value).length > 90 || String(f.value).includes('\n')
          // A newline straight after the tag is dropped by the parser, so one is
          // added: the text put back must be the text taken out, character for
          // character, or an untouched field would look like an edit.
          ? `<textarea id="f-${at}" data-key="${esc(f.key)}" data-was="${esc(f.value)}"
>${esc(f.value)}</textarea>`
          : `<input id="f-${at}" data-key="${esc(f.key)}" data-was="${esc(f.value)}"
             value="${esc(f.value)}">`;
      return `<div class="outgoing__field">
        <label for="f-${at}">${esc(f.label)}</label>${control}</div>`;
    })
    .join('');
  return `<details class="outgoing" open id="out-${esc(a.id)}">
    <summary>What will go out</summary>${rows}
    <p class="outgoing__why">${
      editable
        ? 'Change it here before you say yes. If you change it, Jarvis keeps asking you about this one.'
        : 'This is exactly what gets sent.'
    }</p></details>`;
}

// Returns the edited fields, or null when nothing changed. Only a real change
// may travel: an unchanged field sent back as a change would count against the
// company, because changing something before saying yes means Jarvis keeps
// asking.
function corrections(id) {
  const box = document.getElementById('out-' + id);
  const fields = box ? [...box.querySelectorAll('[data-key]')] : [];
  if (!fields.length) return null;
  const edited = {};
  let changed = false;
  for (const f of fields) {
    edited[f.dataset.key] = f.value;
    if (f.value !== f.dataset.was) changed = true;
  }
  return changed ? edited : null;
}

// The 15-second repaint must not delete what someone is part-way through typing
// into a request they are about to authorise.
export function editing() {
  // Scoped to the region rather than to an id: since M8-4 the approvals region
  // is declared by two workspaces (the Command Center and Approvals) and only
  // the active one is ever filled, so the selector must name the region, not a
  // single element.
  const fields = [...document.querySelectorAll('[data-region="asks"] [data-key]')];
  return (
    fields.some((f) => f.value !== f.dataset.was) ||
    fields.includes(document.activeElement)
  );
}

export function registerApprovalActions() {
  action('decide', async ({ id, verb }) => {
    const body = {};
    if (verb === 'approve') {
      const edited = corrections(id);
      if (edited) body.modified_parameters = edited;
    }
    const res = await post(`/api/approvals/${id}/${verb}`, body);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    refresh();
  });
}
