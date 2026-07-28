// Company cards — level 1 of the progressive disclosure ladder
// (docs/design/10-interaction-patterns.md).
//
// Level 2 left this module at M9-2. It used to be `openCo()`, a modal sheet
// holding one company's entire operational record; it is now a route
// (`#/companies/<id>`, app/company-workspace.js), which survives a reload, can
// be linked, and answers the browser's own Back button. What remains here is
// the card and the actions a card can take.
//
// The controls that reach level 2 are therefore `<a href>`, not buttons: a
// control that navigates is a link, a control that acts is a button, and
// `[data-act]` is for the second kind only
// (docs/design/12-application-shell.md, "Navigation").

import { post } from './api.js';
import { action } from './actions.js';
import { esc, money } from './format.js';
import { flash } from './flash.js';
import { refresh } from './refresh.js';

/** Ten segments, filled to the health score. Not a progress bar — health is a
 *  level that moves both ways.
 *
 *  Exported for the company workspace, which shows the same meter one level
 *  down. Two copies of a ten-segment fill would eventually round differently
 *  and show one company two health readings on two screens. */
export function meter(health, band) {
  const lit = Math.round(health / 10);
  const segs = Array.from(
    { length: 10 },
    (_, i) => `<span class="meter__seg${i < lit ? ' meter__seg--on' : ''}"></span>`,
  ).join('');
  return `<div class="meter meter--${esc(band)}">${segs}</div>`;
}

/** The address of one company's workspace. One definition, so the card, the
 *  truncation affordance and an approval's "Why?" can never point at three
 *  slightly different routes. */
export const companyHref = (id) => `#/companies/${encodeURIComponent(id)}`;

/** A quiet marker that this company's template has an update waiting
 *  (D-030, design PLUGIN-FRAMEWORK.md Part 4/6). Phase-3 gate ruling, M9-F27:
 *  until now the only way to discover a pending update was to open every
 *  company one at a time, which is a search the operator should never have to
 *  run across their own roster.
 *
 *  A MARKER, not a control. The card already has exactly one way in — the
 *  Details link directly beneath this — and a second link to the same
 *  destination would spend the card's one destination affordance twice.
 *
 *  `--accent`, never a status hue: colour on this card means health and
 *  nothing else (ratified M7-5a), and `02-color.md` rule 3 carves the accent
 *  out of that as "an affordance, not a status". It is the same signal the
 *  workspace's own `.pending-update` card carries as its left rule, one level
 *  up and one line long — deliberately NOT `.ask`-shaped, because this is the
 *  platform proposing a change, not a company asking for money.
 *
 *  **Renders nothing today.** `/api/companies` does not carry
 *  `pending_update`; only `/api/companies/{id}` does, and computing it across
 *  the roster from the surface would be N per-company fetches — the exact
 *  cost `12-application-shell.md` refused a cross-company Goals workspace
 *  for. The field this waits on is named in the M9-2c report and in
 *  `06-components.md`; nothing here guesses at it, so the marker appears on
 *  the day the field does and not one repaint sooner. */
function updateFlag(c) {
  return c.pending_update ? `<p class="co-card__update">Update available</p>` : '';
}

// The card carries one meter and one sentence. The three health parts belong
// to the company workspace, not here (ratified M7-5a).
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
    <p class="money">spent <b>${money(c.spent)}</b> of ${money(c.budget)}</p>
    <div class="co-card__doing"><span class="eyebrow">Latest update</span>${esc(c.doing)}${
      c.doing.endsWith('…')
        ? ` <a class="btn--link" href="${companyHref(c.id)}">more in Details</a>`
        : ''
    }</div>
    ${updateFlag(c)}
    <div class="co-card__acts">
      <a class="btn btn--small" href="${companyHref(c.id)}">Details</a>
      <button class="btn btn--small" data-act="toggle-co" data-id="${esc(c.id)}"
        data-running="${c.running ? 'yes' : 'no'}">${c.running ? 'Pause' : 'Start'}</button>
    </div></article>`;
}

export function registerCompanyActions() {
  action('toggle-co', async ({ id, running }) => {
    const res = await post(`/api/companies/${id}/${running === 'yes' ? 'pause' : 'resume'}`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    refresh();
  });

  // These three act on the company workspace. They used to reopen the Details
  // sheet by hand; now the ordinary repaint is the redraw, because the page
  // the operator is standing on is already painted by the repaint cycle.
  action('revoke', async ({ id, grant }) => {
    const res = await post(`/api/companies/${id}/revoke/${grant}`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    refresh();
  });

  // Consent to a pending template update — never the approvals path (D-030).
  action('apply-update', async ({ id }) => {
    const res = await post(`/api/companies/${id}/pending-update/apply`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    refresh();
  });

  action('dismiss-update', async ({ id }) => {
    const res = await post(`/api/companies/${id}/pending-update/dismiss`);
    if (!res.ok) {
      flash(res.message);
      return;
    }
    refresh();
  });
}
