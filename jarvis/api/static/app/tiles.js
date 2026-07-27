// The stat tile row — the Command Center's top line.
//
// Every tile maps to a field the API already serves. A tile whose number has
// no endpoint does not ship: the concept image's "milestone status" tile is
// exactly that case and was dropped rather than faked
// (docs/design/06-components.md, docs/design/01-principles.md #3).
//
// This row replaces the pre-M8 masthead strip. It shows the same facts from
// the same endpoints, given the space to be read at a glance.

import { esc, money, ago, plural } from './format.js';

// `label` and `value` are escaped here. `context` is deliberately NOT — one
// caller needs a `<span>` around the spending-paused sentence — so every value
// interpolated into a `context` string is escaped at its own call site below.
// A `context` built from an API value without esc() would be a hole; there is
// no third option, because the escaping cannot happen in both places.
function tile({ label, value, context, tone }) {
  return `<div class="tile${tone ? ' tile--' + tone : ''}">
    <span class="tile__label">${esc(label)}</span>
    <span class="tile__value">${esc(value)}</span>
    <span class="tile__context">${context}</span>
  </div>`;
}

/**
 * @param summary   /api/summary
 * @param approvals /api/approvals — the same array the attention region
 *                  renders, so the tile and the section heading can never
 *                  disagree about how many decisions are waiting.
 * @param companies /api/companies
 */
export function tileRow(summary, approvals, companies) {
  const paused = summary.companies - summary.running;
  const waiting = approvals.length;
  const oldest = waiting
    ? approvals.reduce((a, b) => (a.waiting_since < b.waiting_since ? a : b))
    : null;
  const needLook = companies.filter((c) => c.health_band !== 'healthy').length;

  return (
    tile({
      label: 'Companies',
      value: `${summary.running} of ${summary.companies}`,
      context: paused
        ? `${esc(paused)} ${plural(paused, 'paused', 'paused')}`
        : 'all running',
    }) +
    tile({
      label: 'Needs your OK',
      value: waiting,
      context: oldest
        ? `oldest waiting ${esc(ago(oldest.waiting_since))}`
        : 'nothing waiting',
      tone: waiting ? 'attention' : '',
    }) +
    tile({
      label: 'Spent today',
      value: money(summary.spent_today),
      context: summary.spending_paused
        ? `<span class="halted">paused — daily limit reached</span>`
        : `of ${esc(money(summary.spend_limit))} limit`,
      tone: summary.spending_paused ? 'attention' : '',
    }) +
    tile({
      label: 'Needs a look',
      value: needLook,
      context: needLook
        ? `${esc(needLook)} ${plural(needLook, 'company', 'companies')} below healthy`
        : 'all companies healthy',
      tone: needLook ? 'attention' : 'healthy',
    })
  );
}
