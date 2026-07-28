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

/** A measured KPI reading, rounded to a size that reads as a measurement
 *  rather than raw float noise. `data_freshness_hours` is the case that
 *  found this (M9-3 surface backlog, M9-F46): a reading of 0.0005 hours interpolated straight into
 *  the goal line as "0.0005 hours since last check" — precision nobody
 *  asked for and nobody can act on. Significant-figure rounding rather than
 *  a fixed decimal count, so a small reading (well under 1) still shows
 *  something meaningful instead of flattening to "0", and a large one shows
 *  a clean whole number instead of a stray ".00". Applies to every goal
 *  reading, not a freshness special case — `metrics_tracked` and
 *  `reports_delivered` are already whole numbers and round-trip unchanged. */
export function measurement(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return String(n);
  if (x === 0) return '0';
  const digits = Math.abs(x) < 1 ? 2 : Math.abs(x) < 10 ? 1 : 0;
  return Number(x.toFixed(digits)).toString();
}
