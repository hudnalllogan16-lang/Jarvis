// The only module that talks to the API. Everything else receives data.

export const get = async (path) => (await fetch(path)).json();

/**
 * POST that never swallows a failure.
 *
 * Returns `{ok: true, status}` or `{ok: false, message}` where `message` is
 * always a sentence an operator can read. The backend sends a plain sentence
 * in `detail`, but the surface stays defensive: §12.5 forbids rendering a raw
 * structure at the operator, and "the backend promised" is not a defence
 * against `[object Object]` reaching a card.
 *
 * `status` (M9-9 product REVISE item 3) is the same defensive read applied to
 * a success: every route in this API already returns `{"status": "..."}` —
 * one plain sentence, D-011-rendered from what the route just did ("Updated.",
 * "Not now.") — and until now no caller ever read it, so an action with no
 * other visible trace (consent to a pending update, unlike Pause/Start's own
 * visible flip) gave the operator nothing back. Absent or malformed, `status`
 * is simply `undefined`; a caller that wants an acknowledgment falls back to
 * its own sentence rather than showing nothing.
 */
export async function post(path, body) {
  const init = { method: 'POST' };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.ok) {
    const payload = await res.json().catch(() => ({}));
    return { ok: true, status: typeof payload.status === 'string' ? payload.status : undefined };
  }
  const failure = await res.json().catch(() => ({}));
  return {
    ok: false,
    message:
      typeof failure.detail === 'string' && failure.detail
        ? failure.detail
        : "That didn't go through. Please try again.",
  };
}
