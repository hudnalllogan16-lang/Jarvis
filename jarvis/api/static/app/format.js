// Formatting primitives shared by every rendering module.
//
// `esc` is the most important function in the surface. Nothing rendered from
// the API is trusted text: the sentences come from stored values a model
// authored, and the approval payload fields are content a company read off the
// open internet. Every value is escaped before it becomes markup — an approval
// card that could be made to run script is a card that could press its own
// Approve button.
//
// The rule is absolute and applies to platform-generated strings too. A value
// being "ours" today is not a property the next change preserves, and the cost
// of escaping a safe string is zero.

const ENTITIES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export const esc = (s) =>
  String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ENTITIES[c]);

/** Money, always two decimals, always with its unit. */
export const money = (n) => '$' + Number(n).toFixed(2);

/** Relative time for feeds and waiting counters. Absolute time belongs in
 *  the audit drill-down, not on a card. */
export function ago(iso) {
  const mins = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  return Math.floor(hrs / 24) + 'd ago';
}

/** `can_do_alone` entries are action-type identifiers ("affiliate.publish_post"),
 *  namespaced machinery — the operator reads what the company can do, not its
 *  dotted internal name. */
export function humanizeAction(actionType) {
  const noPrefix = actionType.includes('.')
    ? actionType.slice(actionType.indexOf('.') + 1)
    : actionType;
  return noPrefix.replace(/_/g, ' ');
}

/** Pluralise a countable noun without the "1 companies" tell. */
export const plural = (n, one, many) => (n === 1 ? one : many);

/** Drop trailing zeros without going through `Number.toString()`, which
 *  switches to exponential notation below 1e-6 — "1e-7 hours since last
 *  check" is machine notation arriving at an operator (§12.5). */
function trimZeros(fixed) {
  return fixed.includes('.') ? fixed.replace(/0+$/, '').replace(/\.$/, '') : fixed;
}

/** A measured KPI reading, rounded to a size that reads as a measurement
 *  rather than as raw float noise. `data_freshness_hours` is the case that
 *  found this (M9-3 surface backlog, M9-F46): 0.0005 interpolated straight
 *  into the goal line as "0.0005 hours since last check" — precision nobody
 *  asked for and nobody can act on.
 *
 *  **Significant figures, not a fixed decimal count** — which is what this
 *  function's own docstring has claimed since M9-3 while the code did the
 *  opposite (M9-F101). `toFixed(2)` on 0.0005 is "0.00", and the round-trip
 *  through `Number()` turned that into **"0"**: the reading that motivated
 *  the function was the one it erased, and it erased it into the one value a
 *  measurement must never be confused with. `10-interaction-patterns.md` is
 *  explicit that zero is a measurement — rendering "very nearly zero" as "0"
 *  is a lie of format in the same family as rendering "unmeasured" as 0.
 *
 *  So: two significant figures below 1, one decimal below 10, whole numbers
 *  above. `metrics_tracked` and `reports_delivered` are already whole and
 *  round-trip unchanged; a true zero stays "0", because it is one. */
export function measurement(n) {
  const x = Number(n);
  // Not "NaN" / "Infinity". The old fallback passed the value through
  // `String()`, which hands an operator a machine token in the middle of a
  // sentence — "NaN hours since last check" (§12.5, M9-F102). Unreachable
  // today, since every caller is served a float; an em dash is what the tile
  // already shows for a value the platform genuinely does not have.
  if (!Number.isFinite(x)) return '—';
  if (x === 0) return '0';
  const mag = Math.abs(x);
  if (mag < 1) {
    // Decimal places needed for two significant figures: 0.0005 -> 5, giving
    // "0.00050" -> "0.0005". Capped because toFixed rejects more than 100 and
    // nothing an operator reads needs anywhere near that.
    const places = Math.min(20, 1 - Math.floor(Math.log10(mag)));
    return trimZeros(x.toFixed(places));
  }
  return trimZeros(x.toFixed(mag < 10 ? 1 : 0));
}
