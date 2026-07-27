// One delegated click listener for the whole surface.
//
// Markup carries `data-act="name"` plus its parameters as data attributes;
// handlers are registered by name. This is a design-system rule, not just an
// implementation detail (docs/design/10-interaction-patterns.md):
//
//   * No inline `onclick`, so no function has to be a global — which is what
//     lets these files be ES modules at all.
//   * `[data-act]` is only ever placed on real controls, so a <div> with a
//     click handler stays structurally impossible.
//   * Re-rendered markup needs no re-binding. The listener lives on `document`
//     and survives every repaint, which is what makes the 15-second refresh
//     cycle cheap.

const handlers = new Map();

/** Register a handler. Called once per action at start-up. */
export function action(name, fn) {
  handlers.set(name, fn);
}

/** Begin dispatching. Called once, from main.js. */
export function startDispatch() {
  document.addEventListener('click', (ev) => {
    const target = ev.target;
    if (!(target instanceof Element)) return;
    const el = target.closest('[data-act]');
    if (!el) return;
    const fn = handlers.get(el.dataset.act);
    if (!fn) return;
    ev.preventDefault();
    fn(el.dataset, el);
  });
}
