// The trend mark — one metric's recorded history
// (docs/design/06-components.md, ".trend").
//
// A DATA mark, not an icon: it renders values, it is inline markup with no
// asset and no request, and it disappears when the values do. That is the same
// family as `.meter`, and it is why 07-iconography.md's bar for adding an icon
// does not apply to it.
//
// Two rules here are load-bearing and neither is a preference:
//
//   1. A line is NEVER drawn through one point. Every real series on the
//      platform today holds exactly one reading (M9-F72), so this is the
//      common case, not the edge: one point renders as one dot against the
//      target, and says so in words. A two-point line invented from a reading
//      and its target would be docs/design/01-principles.md #3's defect with a
//      chart drawn around it.
//   2. The y domain INCLUDES the target. Scaling to the readings alone is the
//      truncated-axis lie — it turns noise into a swing and hides the one
//      comparison a page about goals exists for.
//
// Geometry goes into SVG attributes, never into `style=`: the surface forbids
// inline styles outright (tests/test_design_system.py), which is also the
// reason this is SVG rather than a CSS-drawn bar chart — per-point positions
// in CSS have nowhere to live but a style attribute.

import { esc, measurement } from './format.js';

/** viewBox units. The element is sized in CSS and scales uniformly, so these
 *  are a coordinate space rather than pixels. */
const W = 100;
const H = 28;

/** Keeps the stroke and the latest-reading dot inside the box instead of
 *  clipped in half against its own edge. */
const PAD = 3;

/** How far a lone reading sits from its target line — a fixed distance, never
 *  a scaled one. See `place()`. */
const APART = 7;

const round = (n) => Number(n.toFixed(2));

/** Finite readings only, oldest first (the endpoint already orders them).
 *
 *  A point that is not a number is dropped rather than plotted at zero — a
 *  reading the surface cannot place is not a reading of nothing, and that
 *  distinction is the same one `10-interaction-patterns.md` makes about null
 *  versus zero, arriving here as geometry instead of as text.
 *
 *  The null check is explicit because `Number(null)` is **0**, not `NaN`: a
 *  `Number()`-then-`isFinite` filter looks like it drops empties and silently
 *  plots them on the floor of the chart instead. Caught by feeding the
 *  component a null point rather than by reading it (M9-F86); the route serves
 *  a non-null column today, so nothing was wrong on screen — but a guard whose
 *  comment promises what its code does not do is a guard nobody will re-check. */
function readings(points) {
  return (Array.isArray(points) ? points : [])
    .map((p) => (p == null || p.value == null ? NaN : Number(p.value)))
    .filter(Number.isFinite);
}

/** Where the newest reading stands against its target, direction-aware.
 *
 *  Closes M9-F100, the Phase-3 gate's finding: the chart alone drew Data
 *  freshness (0.0005 against a 24-hour ceiling — excellent) and Reports
 *  delivered (3 against a goal of 4 — short) as the *identical* mark, a dot
 *  below a line, because below-the-line is value space and value space does
 *  not know which way is good. Geometry cannot carry this, so words do.
 *
 *  It closes the accessibility half of the same gap too: the `<svg>` is
 *  `aria-hidden`, so until now the relation existed only as a position and a
 *  screen reader received none of it.
 *
 *  `direction === 'below'` means lower is better (M7-F30 — a freshness reading
 *  of one hour against a 24-hour target is excellent, not a 96% miss), so the
 *  comparison flips rather than the copy.
 *
 *  Placeholder-quality copy; an operator-surface pass is owed on all three. */
function relation(latest, target, direction) {
  if (latest === target) return 'on target';
  const ahead = direction === 'below' ? latest < target : latest > target;
  return ahead ? 'ahead of target' : 'short of it';
}

/** How the readings got to where they are — the trend half of the note.
 *
 *  "up from" / "down from" compares the newest reading with the oldest one
 *  held. It states a fact about the data and no judgement about it: whether up
 *  is good is what `relation()` answers, once, so that the two halves cannot
 *  contradict each other. */
function movement(values, unit) {
  if (values.length < 2) return 'one reading so far — a trend needs a second';
  const first = values[0];
  const last = values[values.length - 1];
  const count = `${values.length} readings`;
  if (last === first) return `${count}, unchanged`;
  const way = last > first ? 'up from' : 'down from';
  return `${count}, ${way} ${esc(measurement(first))} ${esc(unit)}`;
}

/** The sentence beneath the chart — the accessible equivalent of the drawing,
 *  not a caption for it. The `<svg>` is `aria-hidden`, so everything the chart
 *  says has to be sayable here, in greyscale and out loud.
 *
 *  Two facts, in the order an operator wants them: **where it stands**, then
 *  **how it got there**. A metric with no target has no relation to state and
 *  falls back to the movement alone. */
function note(values, s) {
  const latest = values[values.length - 1];
  const target = Number(s.target);
  const how = movement(values, s.unit);
  if (!Number.isFinite(target)) return how;
  return `${relation(latest, target, s.direction)} &middot; ${how}`;
}

/**
 * Render one metric's history, or nothing.
 *
 * @param s a `/api/companies/{id}/kpi-series` entry — `{unit, target,
 *          points: [{when, value}]}`. Called with a plain goal reading too
 *          (no `points`), which has no history to draw and correctly
 *          produces nothing: that is the graceful path when the series read
 *          is unavailable, and it lands the page exactly where it was before
 *          this component existed.
 */
/**
 * Vertical placement for the readings and the target line.
 *
 * Two regimes, because one reading and several readings know different things.
 *
 * **Several readings** scale to the domain of the readings *and* the target.
 * Scaling to the readings alone is the truncated-axis lie; including the
 * target is what makes "heading toward the line or away from it" readable.
 *
 * **One reading has no scale at all**, and this is the case nearly all the
 * live data is in (M9-F72). Its domain would be exactly {reading, target}, so
 * the two always land on opposite edges of the box and a one-unit shortfall
 * draws identically to a thousand-unit one — the eye reads that distance as
 * magnitude, and it is not magnitude, it is an artifact of having two numbers.
 * So a lone reading is placed a FIXED distance above, on, or below its target.
 * The chart then states the relation, which is knowable, and no magnitude,
 * which is not; the exact figures are in the line directly above it.
 *
 * Above and below are in VALUE space, not in "good" space — a lower-is-better
 * metric puts a good reading below the line (M7-F30), and which way is good is
 * what the sentence above says ("goal is at most 24 hours since last check").
 */
function place(values, target, hasTarget) {
  const mid = H / 2;
  if (values.length < 2) {
    const v = values[0];
    const apart = !hasTarget || v === target ? 0 : v > target ? -APART : APART;
    return { y: () => round(mid + apart), targetY: mid, scaled: false };
  }
  const domain = hasTarget ? values.concat(target) : values;
  let lo = Math.min(...domain);
  let hi = Math.max(...domain);
  // A flat series sitting exactly on its target would divide by zero.
  // Widening puts the whole thing mid-box, which is honest: there is nothing
  // to spread out.
  if (hi === lo) {
    lo -= 1;
    hi += 1;
  }
  const span = H - PAD * 2;
  const y = (v) => round(PAD + span * (1 - (v - lo) / (hi - lo)));
  return { y, targetY: hasTarget ? y(target) : null, scaled: true };
}

export function trendMark(s) {
  const values = readings(s && s.points);
  if (!values.length) return '';

  const target = Number(s.target);
  const hasTarget = Number.isFinite(target);
  const { y, targetY } = place(values, target, hasTarget);
  const x = (i) => round(values.length < 2 ? W / 2 : (W * i) / (values.length - 1));

  const targetLine =
    targetY === null
      ? ''
      : `<line class="trend__target" x1="0" y1="${targetY}" x2="${W}" y2="${targetY}"/>`;
  const line =
    values.length > 1
      ? `<polyline class="trend__line" points="${values
          .map((v, i) => `${x(i)},${y(v)}`)
          .join(' ')}"/>`
      : '';
  const newest = values.length - 1;

  return `<div class="trend">
    <svg class="trend__chart" viewBox="0 0 ${W} ${H}" aria-hidden="true"
      focusable="false">${targetLine}${line}<circle class="trend__now"
      cx="${x(newest)}" cy="${y(values[newest])}" r="2"/></svg>
    <p class="trend__note">${note(values, s)}</p>
  </div>`;
}
