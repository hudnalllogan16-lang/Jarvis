// Theme persistence for the Settings control (M9-3 surface backlog item 8,
// M9-F47; docs/design/02-color.md: "the mechanism is complete and testable now; the
// control comes with the frame that holds it" — the Application Shell is
// that frame, and Settings is where its own text places the control).
//
// A plain cookie, not `localStorage`/`sessionStorage`: the surface's rule is
// "no browser storage APIs", named as the two Web Storage APIs this module
// never touches. A cookie is also the only mechanism `index.html`'s
// synchronous bootstrap script can read before first paint — a Storage API
// read could not happen any earlier than this module's own (deferred, ES
// module) load, so it could not prevent the flash the bootstrap script
// exists to avoid. Same cookie, read in both places; this module owns
// writing it.
//
// No server round trip: the choice never needs to be known anywhere but the
// browser that made it, so there is no new persistence mechanism, no new
// route, and nothing for docs/DECISIONS.md to record.

const COOKIE = 'jarvis_theme';
const YEAR = 60 * 60 * 24 * 365;

function readCookie() {
  const m = document.cookie.match(new RegExp('(?:^|; )' + COOKIE + '=(dark|light)'));
  return m ? m[1] : 'system';
}

/** 'system' (no explicit choice — honours the OS default), 'dark', or 'light'. */
export function currentTheme() {
  return readCookie();
}

/** Apply and persist a theme choice. 'system' clears both the attribute and
 *  the cookie, returning the surface to `prefers-color-scheme`.
 *
 *  M9-F25 ("transition smear", found live on the M9-2 company workspace):
 *  several components declare their own hover/colour transition
 *  (`--motion-quick` on `.btn`, `--motion-slow` on `.btn--primary` and
 *  `.section-head--urgent` — docs/design/08-motion.md #2–3). Those exist to
 *  report a state change happening TO an element; a theme swap is the
 *  operator's own deliberate action, already reported by the control they
 *  just used, so letting every element fade to its new colours on its own
 *  unrelated timing reads as a messy smear instead of one clean change.
 *  `.theme-swap` (base.css) kills every transition for exactly this repaint,
 *  the same shape `prefers-reduced-motion` already uses for a session-long
 *  preference, applied here for one swap instead. */
export function setTheme(value) {
  const html = document.documentElement;
  html.classList.add('theme-swap');
  if (value === 'system') {
    html.removeAttribute('data-theme');
    document.cookie = `${COOKIE}=; path=/; max-age=0`;
  } else {
    html.setAttribute('data-theme', value);
    document.cookie = `${COOKIE}=${value}; path=/; max-age=${YEAR}; samesite=lax`;
  }
  // Force the new values to commit before transitions come back next frame —
  // without this the class removal could be batched with the attribute
  // change and the swap would still animate.
  void html.offsetHeight;
  requestAnimationFrame(() => html.classList.remove('theme-swap'));
}
