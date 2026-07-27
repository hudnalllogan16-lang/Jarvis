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
