// The only module that talks to the API. Everything else receives data.

export const get = async (path) => (await fetch(path)).json();

/**
 * POST that never swallows a failure.
 *
 * Returns `{ok: true}` or `{ok: false, message}` where `message` is always a
 * sentence an operator can read. The backend sends a plain sentence in
 * `detail`, but the surface stays defensive: §12.5 forbids rendering a raw
 * structure at the operator, and "the backend promised" is not a defence
 * against `[object Object]` reaching a card.
 */
export async function post(path, body) {
  const init = { method: 'POST' };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.ok) return { ok: true };
  const failure = await res.json().catch(() => ({}));
  return {
    ok: false,
    message:
      typeof failure.detail === 'string' && failure.detail
        ? failure.detail
        : "That didn't go through. Please try again.",
  };
}
