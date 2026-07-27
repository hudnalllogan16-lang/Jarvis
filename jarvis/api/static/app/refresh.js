// A one-line indirection that keeps the module graph acyclic.
//
// Feature modules need to trigger a repaint after an action succeeds, and
// main.js needs to import those feature modules to register their handlers.
// Importing main.js back from a feature module would close that cycle; this
// tiny seam breaks it instead.

let handler = () => {};

/** main.js installs the real repaint here at start-up. */
export function setRefresh(fn) {
  handler = fn;
}

/** Repaint every region. Safe to call before setRefresh (no-op). */
export function refresh() {
  return handler();
}
