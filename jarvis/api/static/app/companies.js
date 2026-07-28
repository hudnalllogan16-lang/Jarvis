// Company cards and the Details panel — levels 1 and 2 of the progressive
// disclosure ladder (docs/design/10-interaction-patterns.md).

import { get, post } from './api.js';
import { action } from './actions.js';
import { esc, money, ago, humanizeAction, measurement } from './format.js';
import { flash } from './flash.js';
import { openSheet, sheet, closeSheet } from './panel.js';
import { refresh } from './refresh.js';

/** Ten segments, filled to the health score. Not a progress bar — health is a
 *  level that moves both ways. */
function meter(health, band) {
  const lit = Math.round(health / 10);
  const segs = Array.from(
    { length: 10 },
    (_, i) => `<span class="meter__seg${i < lit ? ' meter__seg--on' : ''}"></span>`,
  ).join('');
  return `<div class="meter meter--${esc(band)}">${segs}</div>`;
}

// The card carries one meter and one sentence. The three health parts belong
// to Details, not here (ratified M7-5a).
export function coCard(c) {
  return `<article class="co-card co-card--${esc(c.health_band)} ${
    c.running ? 'co-card--running' : 'co-card--paused'
  }">
    <div class="co-card__top">
      <div class="co-card__name">${esc(c.name)}</div>
      <div class="co-card__state"><span class="dot"></span>${esc(c.status)}</div>
    </div>
    <p class="kind">${esc(c.kind)}</p>
    <div>
      <div class="meter__row"><span>Health</span>
        <span class="meter__value">${esc(c.health)}</span></div>
      ${meter(c.health, c.health_band)}
      <p class="reason">${esc(c.health_reason)}</p>
    </div>
    <p class="co-card__money">spent <b>${money(c.spent)}</b> of ${money(c.budget)}</p>
    <div class="co-card__doing"><span class="eyebrow">Latest update</span>${esc(c.doing)}${
      c.doing.endsWith('…')
        ? ` <button type="button" class="btn--link" data-act="open-co"
             data-id="${esc(c.id)}">more in Details</button>`
        : ''
    }</div>
    <div class="co-card__acts">
      <button class="btn btn--small" data-act="open-co"
        data-id="${esc(c.id)}">Details</button>
      <button class="btn btn--small" data-act="toggle-co" data-id="${esc(c.id)}"
        data-running="${c.running ? 'yes' : 'no'}">${c.running ? 'Pause' : 'Start'}</button>
    </div></article>`;
}

// One line of the goals drill-down: what was measured against what it was
// measured against, in the metric's own unit. "at most"/"at least" reads the
// target the direction the metric actually runs — a lower-is-better reading
// (data freshness) is not "behind" for being small.
function goalLine(g) {
  const goal = g.direction === 'below' ? 'at most' : 'at least';
  // `measurement()` rounds to a size that reads as a reading rather than raw
  // float noise (M9-3 surface backlog, M9-F46: "0.0005 hours since last
  // check" for data freshness) — applied to every goal, not just freshness's.
  return `<div class="entry"><p>${esc(g.label)}</p>
     <p class="entry__why">${esc(measurement(g.measured))} ${esc(g.unit)} &middot; goal is ${goal} ${esc(
       measurement(g.target),
     )} ${esc(g.unit)}</p></div>`;
}

// When every target is still unmeasured, one clean sentence replaces what
// would otherwise be a list of individually stuttering "not measured yet"
// entries, one per target (M7-5b item 3).
function goalsSection(goals) {
  if (!goals || !goals.length) {
    return '<p class="calm">No goals set for this company yet.</p>';
  }
  if (goals.every(g => g.measured === null)) {
    return '<p class="calm">Nothing measured yet — check back after its next work session.</p>';
  }
  return goals
    .map((g) =>
      g.measured === null
        ? `<div class="entry"><p>${esc(g.label)}</p>
           <p class="entry__why">Not measured yet.</p></div>`
        : goalLine(g),
    )
    .join('');
}

// A pending template update (design PLUGIN-FRAMEWORK.md Part 4/6, D-030).
// Every sentence here is server-rendered from stored values (D-011) — this
// function only escapes and lays them out. Deliberately not `.ask`-shaped:
// an accent rule, never the risk-red an approval uses, because this is the
// platform proposing a change, not a company asking for money.
function pendingUpdateCard(id, u) {
  if (!u) return '';
  const changes = (u.changes || []).map((c) => `<li>${esc(c)}</li>`).join('');
  return `<div class="pending-update">
    <p class="pending-update__headline">${esc(u.headline)}</p>
    <p class="pending-update__intro">${esc(u.intro)}</p>
    <ul class="pending-update__changes">${changes}</ul>
    <div class="acts acts--plain">
      <button class="btn btn--primary" data-act="apply-update"
        data-id="${esc(id)}">Review and apply</button>
      <button class="btn" data-act="dismiss-update" data-id="${esc(id)}">Not now</button>
    </div></div>`;
}

export async function openCo(id) {
  const c = await get(`/api/companies/${id}`);
  const stuck = (c.stuck || [])
    .map((s) => `<div class="stuck">${esc(s.what)}</div>`)
    .join('');
  const alone = (c.can_do_alone || [])
    .map(
      (a) =>
        `<div class="entry"><p>${esc(c.name)} can now do this on its own: ${esc(
          humanizeAction(a),
        )}
     <button class="btn btn--small" data-act="revoke" data-id="${esc(id)}"
       data-grant="${esc(a)}">Undo</button></p></div>`,
    )
    .join('');
  const feed =
    (c.activity || [])
      .map(
        (e) =>
          `<div class="entry"><time datetime="${esc(e.when)}">${esc(ago(e.when))}</time>
     <p>${esc(e.what)}</p>
     <p class="entry__why">${esc(e.why)}</p></div>`,
      )
      .join('') ||
    `<div class="entry"><p class="entry__why">Nothing has happened yet.</p></div>`;
  // "/100" is explicit on every part rather than three bare numbers sitting one
  // line above a dollar amount that could be mistaken for the same kind of
  // figure (M7-5b item 2).
  const parts = Object.entries(c.health_parts || {})
    .map(
      ([label, val]) =>
        `<div class="health-parts__item"><span>${esc(label)}</span><b>${esc(val)}/100</b></div>`,
    )
    .join('');

  openSheet(`
    <h2 id="sheetTitle">${esc(c.name)}</h2>
    <p class="kind">${esc(c.kind)}</p>
    <p class="kind-desc">${esc(c.kind_description)}</p>
    ${pendingUpdateCard(id, c.pending_update)}
    ${
      c.pending_update_note
        ? `<p class="calm">${esc(c.pending_update_note)}</p>`
        : ''
    }
    <p class="reason reason--tight">${esc(c.health_reason)}
       &middot; health ${esc(c.health)}</p>
    <div class="health-parts">${parts}</div>
    <p class="co-card__money">spent <b>${money(c.spent)}</b> of ${money(c.budget)}
       &middot; most per work session <b>${money(c.per_round_limit)}</b></p>
    ${stuck}${alone}
    <details><summary>Hitting its goals, in detail</summary>${goalsSection(c.goals)}</details>
    <h3 class="section-head">What ${esc(c.name)} is doing</h3>
    ${feed}
    <details id="fullDetails"><summary>Full details</summary><pre id="raw">Loading…</pre></details>
    <div class="acts acts--plain">
      <button class="btn" data-act="close-sheet">Close</button></div>`);

  // Raw audit detail is fetched only when the operator opens it. Drill-down is
  // opt-in per §12.5, and loading it eagerly would make it part of the default
  // view in everything but appearance.
  //
  // Bound by id, not by `querySelector('details')` — that selector returned the
  // FIRST disclosure in the sheet, which is the goals section, so "Full
  // details" sat on "Loading…" forever unless the operator happened to open
  // goals first (finding M8-F25).
  sheet()
    .querySelector('#fullDetails')
    .addEventListener('toggle', async (ev) => {
      if (ev.target.open && !ev.target.dataset.loaded) {
        ev.target.dataset.loaded = '1';
        document.getElementById('raw').textContent = JSON.stringify(
          await get(`/api/companies/${id}/full-details`),
          null,
          2,
        );
      }
    });
}

export function registerCompanyActions() {
  action('open-co', ({ id }) => openCo(id));
  action('close-sheet', () => closeSheet());

  action('toggle-co', async ({ id, running }) => {
    const res = await post(`/api/companies/${id}/${running === 'yes' ? 'pause' : 'resume'}`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    refresh();
  });

  action('revoke', async ({ id, grant }) => {
    const res = await post(`/api/companies/${id}/revoke/${grant}`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    openCo(id);
  });

  // Consent to a pending template update — never the approvals path (D-030).
  action('apply-update', async ({ id }) => {
    const res = await post(`/api/companies/${id}/pending-update/apply`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    openCo(id);
  });

  action('dismiss-update', async ({ id }) => {
    const res = await post(`/api/companies/${id}/pending-update/dismiss`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    openCo(id);
  });
}
