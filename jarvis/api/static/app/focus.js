// Focus containment for the shell's two overlays: the modal sheet and the
// rail when it is an overlay rather than docked.
//
// Closes finding M8-F23 (WCAG 2.4.3, "Focus Order"): before this module the
// modal sheet trapped nothing — Tab from inside the open panel walked into the
// page behind it, which a screen-reader or keyboard-only operator reads as the
// dialog having silently closed — and focus was never returned to the control
// that opened it, so closing a panel dropped the operator at the top of the
// document.
//
// One module, two callers, because the rail overlay has exactly the same two
// obligations as the sheet and solving it twice is how they drift apart.

/** Everything that can hold focus, in DOM order — which is reading order
 *  (docs/design/09-accessibility.md: nothing here uses a positive tabindex).
 *  `summary` is included: the disclosure is a real control and the audit
 *  drill-down is reached through one. */
const FOCUSABLE = [
  'a[href]',
  'button:not(:disabled)',
  'input:not(:disabled)',
  'select:not(:disabled)',
  'textarea:not(:disabled)',
  'summary',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Visible focusable descendants. `offsetParent` is null for anything
 *  `display:none`, which is how a collapsed disclosure's contents stay out of
 *  the cycle without being enumerated separately. */
function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(
    (node) => node.offsetParent !== null || node === document.activeElement,
  );
}

/** Move focus to the first thing inside `root`, or to `root` itself when it
 *  holds no controls yet. */
export function focusFirst(root) {
  const first = focusables(root)[0];
  (first || root).focus();
}

/**
 * Contain Tab inside `root` and remember where focus came from.
 *
 * Returns a `release()` that removes the containment and puts focus back on
 * the invoking control. If that control no longer exists — the surface
 * repaints every 15 seconds, so a panel left open across a cycle outlives the
 * button that opened it — focus lands on the workspace instead of being
 * dropped on `<body>`, where a keyboard operator would have to tab from the
 * top of the document to get back.
 *
 * The listener is registered in the capture phase so it sees Tab before any
 * handler inside the sheet can.
 */
export function trapFocus(root, fallback) {
  // `document.activeElement` is <body> when nothing holds focus — opening an
  // overlay by pointer, or from a control that was itself just replaced by a
  // repaint. Restoring focus TO <body> is a silent no-op that drops the
  // keyboard operator at the top of the document, which is the half of
  // M8-F23 that is easiest to believe is fixed when it is not. Found by
  // live keyboard verification, not by inspection.
  const active = document.activeElement;
  const invoker = active && active !== document.body && active !== document.documentElement
    ? active
    : null;

  const onKey = (ev) => {
    if (ev.key !== 'Tab') return;
    const items = focusables(root);
    if (!items.length) {
      ev.preventDefault();
      root.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const inside = root.contains(document.activeElement);
    if (ev.shiftKey && (document.activeElement === first || !inside)) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && (document.activeElement === last || !inside)) {
      ev.preventDefault();
      first.focus();
    }
  };

  document.addEventListener('keydown', onKey, true);

  return function release() {
    document.removeEventListener('keydown', onKey, true);
    const back = invoker && invoker.isConnected ? invoker : fallback;
    if (back && back.isConnected) back.focus();
  };
}
