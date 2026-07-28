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
import { companyHref } from './companies.js';

// `label` and `value` are escaped here. `context` is deliberately NOT — a
// couple of callers need markup around part of the sentence (the
// spending-paused reason, the census tile's worst-company link) — so every
// value interpolated into a `context` string is escaped at its own call site
// below. A `context` built from an API value without esc() would be a hole;
// there is no third option, because the escaping cannot happen in both places.
//
// Exported since M9-2: the company workspace builds a tile row of its own from
// per-company fields. It reuses this primitive rather than growing a second
// one, so the tile keeps one anatomy, one set of tones and one escaping
// contract wherever it appears (docs/design/06-components.md, extend-first).
export function tile({ label, value, context, tone }) {
  return `<div class="tile${tone ? ' tile--' + tone : ''}">
    <span class="tile__label">${esc(label)}</span>
    <span class="tile__value">${esc(value)}</span>
    <span class="tile__context">${context}</span>
  </div>`;
}

/** The "Needs a look" tile's context line: the portfolio census (design
 * EXECUTIVE-LAYER.md Part 3, D-039) — counts per band, plus the worst
 * company named as a link to its own workspace, never a portfolio score.
 * `never measured` is its own, separate count (D-039, the one honest
 * limitation stated rather than smoothed) — a young company with nothing
 * recorded yet is not evidence about the portfolio's health either way, so
 * it is reported and folded into neither `healthy` nor `watch`/`at_risk`.
 *
 * The worst company's own reason is read back from `companies` — already
 * fetched and already carrying `health_reason` for the card itself — rather
 * than asked of the census a second time, so the sentence here can never
 * drift from the one the card shows for the same company (D-011's "never
 * regenerate a rendered number" applied to a rendered sentence instead).
 *
 * `census.worst_company` is a link, never a second destination beside one
 * that already exists on the card: it is the SAME `#/companies/<id>` route
 * `coCard`'s own "Details" link opens, just reached from a different place.
 */
function censusContext(census, companies) {
  const parts = [
    `healthy ${census.healthy}`,
    `watch ${census.watch}`,
    `at risk ${census.at_risk}`,
  ];
  if (census.never_measured) parts.push(`never measured ${census.never_measured}`);
  const counts = esc(parts.join(' · '));

  const worst = census.worst_company && companies.find((c) => c.id === census.worst_company.id);
  if (!worst) return counts;
  const reason = worst.health_reason ? ` — ${esc(worst.health_reason)}` : '';
  return (
    `${counts} — <a class="btn--link" href="${companyHref(worst.id)}">${esc(worst.name)}</a> ` +
    `needs a look${reason}`
  );
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
  const census = summary.census;
  const needLook = census.watch + census.at_risk;
  // A company merely at `watch` must not push this tile to the same risk-red
  // a real `at_risk` company earns — the card beside it already keeps the
  // two apart (M9-3 surface backlog, M9-F42: tile-vs-card severity tone
  // mismatch).
  const anyAtRisk = census.at_risk > 0;

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
        ? `<span class="halted">${esc(
            summary.spending_paused_reason || 'paused — daily limit reached',
          )}</span>`
        : `of ${esc(money(summary.spend_limit))} limit`,
      tone: summary.spending_paused ? 'attention' : '',
    }) +
    tile({
      label: 'Needs a look',
      value: needLook,
      // Never-measured is reported even when nothing needs a look (D-039:
      // its own count, folded into neither `healthy` nor a look-worthy band)
      // — a portfolio can be "nothing wrong" and "one company unmeasured" at
      // once, and the second fact must not go silent just because the first
      // one is good news.
      context:
        needLook || census.never_measured
          ? censusContext(census, companies)
          : 'all companies healthy',
      tone: needLook ? (anyAtRisk ? 'attention' : 'watch') : 'healthy',
    })
  );
}
