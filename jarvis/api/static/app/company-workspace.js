// One company, as a place rather than as a dialog — level 2 of the
// progressive-disclosure ladder (docs/design/13-company-workspace.md).
//
// This module owns everything the Details SHEET used to own. The sheet was not
// kept alongside it: docs/design/10-interaction-patterns.md allows exactly
// three levels, and a workspace shipped beside the sheet would have been a
// fourth — plus a second copy of the same fields, diverging on the first
// change either one received. So `openCo()` is gone, and the controls that
// used to open it are links to `#/companies/<id>`.
//
// Everything on this page is backed by a field the API already serves; the
// table of which field, from which endpoint, is in the design document. The
// one thing the page deliberately does NOT draw is a trend — `kpi_values` is a
// real series but no route serves it, and a line through one point is not a
// trend (reserved, with the shape it needs, in 13-company-workspace.md).

import { get } from './api.js';
import { esc, money, ago, humanizeAction, measurement } from './format.js';
import { meter } from './companies.js';
import { tile } from './tiles.js';
import { region, setWorkspaceTitle } from './shell.js';

/** The health band as a word. Colour never carries a state alone
 *  (docs/design/09-accessibility.md), and the tile has no meter to lean on.
 *  Placeholder-quality copy — an operator-surface pass is owed on all three. */
const BAND_WORDS = {
  healthy: 'healthy',
  watch: 'worth a look',
  at_risk: 'needs attention',
};

// One line of the goals drill-down: what was measured against what it was
// measured against, in the metric's own unit. "at most"/"at least" reads the
// target the direction the metric actually runs — a lower-is-better reading
// (data freshness) is not "behind" for being small.
//
// No percentage is computed here, deliberately. Attainment is direction-aware
// (KpiEngine.attainment), and deriving it a second time in JavaScript would
// put one rule in two languages; the aggregate on this page comes from
// `health_parts`, server-computed. See the design document's arithmetic rule.
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

/** The summary band. Four facts that orient the operator before they read —
 *  which is a different job from the company CARD's one well-chosen fact, and
 *  the reason the "level 1 is not a summary of level 2" rule is not broken
 *  here (docs/design/13-company-workspace.md, "Section order").
 *
 *  Health takes the healthy tone or none. It deliberately does NOT escalate a
 *  `watch` band to the attention tone: `watch` means worth a look, and
 *  spending the risk colour on it leaves nothing louder for a company that is
 *  actually at risk. */
function tiles(c, approvals) {
  const goals = c.goals || [];
  const measured = goals.filter((g) => g.measured !== null).length;
  const waiting = approvals.length;
  const oldest = waiting
    ? approvals.reduce((a, b) => (a.waiting_since < b.waiting_since ? a : b))
    : null;

  return (
    tile({
      label: 'Health',
      value: c.health,
      context: esc(BAND_WORDS[c.health_band] || c.health_band),
      tone: c.health_band === 'healthy' ? 'healthy' : '',
    }) +
    tile({
      label: 'Goals measured',
      // Counting array members is not recomputing a score: this says how much
      // of the picture exists, never whether the picture is good.
      value: goals.length ? `${measured} of ${goals.length}` : '—',
      // The context line agrees with the section below it. "against its own
      // targets" beside a `0 of 1` invites the reading that the company missed
      // one; the section says nothing has been measured, and so does this.
      context: !goals.length
        ? 'no goals set yet'
        : measured
          ? 'against its own targets'
          : 'nothing measured yet',
    }) +
    tile({
      label: 'Spent',
      value: money(c.spent),
      context: `of ${esc(money(c.budget))}`,
    }) +
    tile({
      label: 'Needs your OK',
      value: waiting,
      context: oldest
        ? `oldest waiting ${esc(ago(oldest.waiting_since))}`
        : 'nothing waiting',
      tone: waiting ? 'attention' : '',
    })
  );
}

/** Identity, state, the one control that changes it, and the summary band.
 *  Painted separately from the body so it keeps refreshing while the body is
 *  held for an open disclosure. */
function headMarkup(c, approvals) {
  return `<a class="ws-back" href="#/companies"><span aria-hidden="true">&lsaquo;</span>
      All companies</a>
    <header class="co-head${c.running ? '' : ' co-head--paused'}">
      <div>
        <!-- Not a heading: the top bar's <h1> already IS this company's name
             on this route, and a duplicate one level down makes a screen
             reader announce it twice. Same shape as .co-card__name, which is
             a div for the same reason. -->
        <p class="co-head__name">${esc(c.name)}</p>
        <p class="kind">${esc(c.kind)}</p>
        <p class="kind-desc">${esc(c.kind_description)}</p>
      </div>
      <div class="co-head__acts">
        <span class="co-head__status"><span class="dot${
          c.running ? ' dot--running' : ''
        }"></span>${esc(c.status)}</span>
        <button class="btn btn--small" data-act="toggle-co" data-id="${esc(c.id)}"
          data-running="${c.running ? 'yes' : 'no'}">${c.running ? 'Pause' : 'Start'}</button>
      </div>
    </header>
    <div class="tile-row">${tiles(c, approvals)}</div>
    ${pendingUpdateCard(c.id, c.pending_update)}
    ${
      c.pending_update_note
        ? `<p class="calm">${esc(c.pending_update_note)}</p>`
        : ''
    }`;
}

/** Work that stopped and has not been picked back up. Rendered only when there
 *  is some: an absent problem needs no container, and the health reason beside
 *  it already reads "Nothing stuck". */
function stuckSection(c) {
  const stuck = c.stuck || [];
  if (!stuck.length) return '';
  return `<h2 class="section-head section-head--urgent">Needs attention
      <span class="section-head__count">${stuck.length}</span></h2>
    ${stuck.map((s) => `<div class="stuck">${esc(s.what)}</div>`).join('')}`;
}

/** Autonomy grants, with the empty state that teaches how one is earned — an
 *  operator who has never seen a grant has no way to know they exist. */
function aloneSection(c, name) {
  const grants = c.can_do_alone || [];
  if (!grants.length) {
    return `<p class="calm">Nothing yet. When you have said yes to the same kind of
      request enough times, Jarvis stops asking about that one and does it on its own —
      it appears here, with an Undo.</p>`;
  }
  return grants
    .map(
      (a) =>
        `<div class="entry"><div class="entry__row">
       <p>${esc(name)} can now do this on its own: ${esc(humanizeAction(a))}</p>
       <button class="btn btn--small entry__act" data-act="revoke" data-id="${esc(c.id)}"
         data-grant="${esc(a)}">Undo</button></div></div>`,
    )
    .join('');
}

function feedSection(c) {
  const feed = c.activity || [];
  if (!feed.length) {
    return `<div class="entry"><p class="entry__why">Nothing has happened yet.</p></div>`;
  }
  return feed
    .map(
      (e) =>
        `<div class="entry"><time datetime="${esc(e.when)}">${esc(ago(e.when))}</time>
     <p>${esc(e.what)}</p>
     <p class="entry__why">${esc(e.why)}</p></div>`,
    )
    .join('');
}

/** The split: what is happening on the left, what the numbers are on the
 *  right. "/100" is explicit on every health part rather than three bare
 *  numbers sitting a line above a dollar amount that could be mistaken for the
 *  same kind of figure (M7-5b item 2). */
function bodyMarkup(c) {
  const parts = Object.entries(c.health_parts || {})
    .map(
      ([label, val]) =>
        `<div class="health-parts__item"><span>${esc(label)}</span><b>${esc(val)}/100</b></div>`,
    )
    .join('');

  return `<div class="co-layout">
    <div class="co-layout__main">
      ${stuckSection(c)}
      <h2 class="section-head">Hitting its goals</h2>
      ${goalsSection(c.goals)}
      <h2 class="section-head">What ${esc(c.name)} is doing</h2>
      ${feedSection(c)}
      <details id="fullDetails"><summary>Full details</summary>
        <pre id="raw">Loading…</pre></details>
    </div>
    <div class="co-layout__side">
      <div class="meter__row"><span>Health</span>
        <span class="meter__value">${esc(c.health)}</span></div>
      ${meter(c.health, c.health_band)}
      <p class="reason reason--tight">${esc(c.health_reason)}</p>
      <div class="health-parts">${parts}</div>
      <h2 class="section-head">Money</h2>
      <p class="money">spent <b>${money(c.spent)}</b> of ${money(c.budget)}</p>
      <p class="money">most per work session <b>${money(c.per_round_limit)}</b></p>
      <h2 class="section-head">What it can do on its own</h2>
      ${aloneSection(c, c.name)}
    </div>
  </div>`;
}

const NOT_FOUND = `<div class="empty"><p>That company isn't here</p>
  <span>This address doesn't match any company Jarvis has. It may have been removed,
  or the link may be incomplete.</span>
  <div class="empty__act">
    <a class="btn btn--primary" href="#/companies">All companies</a></div></div>`;

/** True while the operator has the audit record open.
 *
 *  Reading in depth is work too (docs/design/10-interaction-patterns.md rule
 *  2). Replacing the body would destroy the `<details>` element itself — it
 *  snaps shut and the record it fetched is gone — which is the same defect as
 *  deleting half-typed text in an approval, reached from the other direction.
 *  Level 2 never repainted before M9-2, because it was a modal; that is why
 *  this rule had nowhere to be discovered until now. */
function readingInDepth() {
  const box = document.getElementById('fullDetails');
  return !!box && box.open;
}

/**
 * Paint the company workspace.
 *
 * @param id        the company this route addresses
 * @param approvals /api/approvals — the same array the attention region
 *                  renders, already filtered to this company by the caller,
 *                  so the tile and the queue beneath it can never disagree.
 */
export async function paintCompany(id, approvals) {
  const head = region('company-head');
  const body = region('company-body');
  if (!head || !body) return;

  const c = await get(`/api/companies/${encodeURIComponent(id)}`);
  // A hand-edited address is not an exception the surface may fail silently
  // on. `get` resolves a 404 body like any other, so the shape is the check.
  if (!c || !c.id) {
    head.innerHTML = NOT_FOUND;
    body.innerHTML = '';
    return;
  }

  setWorkspaceTitle(c.name);
  head.innerHTML = headMarkup(c, approvals);
  if (readingInDepth()) return;
  body.innerHTML = bodyMarkup(c);

  // Raw detail is fetched only when the operator opens it. Drill-down is
  // opt-in per §12.5, and loading it eagerly would make it part of the default
  // view in everything but appearance. Bound by id rather than by
  // `querySelector('details')`, which returned the FIRST disclosure on the
  // page and left this one on "Loading…" forever (finding M8-F25).
  document.getElementById('fullDetails').addEventListener('toggle', async (ev) => {
    if (ev.target.open && !ev.target.dataset.loaded) {
      ev.target.dataset.loaded = '1';
      document.getElementById('raw').textContent = JSON.stringify(
        await get(`/api/companies/${encodeURIComponent(id)}/full-details`),
        null,
        2,
      );
    }
  });
}
