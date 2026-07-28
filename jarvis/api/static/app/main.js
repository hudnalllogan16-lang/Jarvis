// Composition root for the operator surface.
//
// This module owns start-up and the repaint cycle; every other module owns one
// region and knows nothing about the others. Nothing here builds markup.
//
// Since M8-4 the surface is a shell with several workspaces, and painting is
// scoped by `region()`: a module writes into the named region of the ACTIVE
// workspace and does nothing when the operator is looking elsewhere. That is
// what keeps the repaint cheap and what keeps two panes from ever holding the
// same region's markup — and therefore the same element ids — at once.

import { get } from './api.js';
import { startDispatch } from './actions.js';
import { startPanel } from './panel.js';
import { startShell, region, navCount, currentRoute } from './shell.js';
import { setRefresh } from './refresh.js';
import { tileRow } from './tiles.js';
import { asksRegion, editing, registerApprovalActions } from './approvals.js';
import { coCard, registerCompanyActions } from './companies.js';
import { paintCompany } from './company-workspace.js';
import { paintHealth, paintNotes, paintSettings, registerSystemActions } from './system.js';
import { registerNewCoActions } from './newco.js';

async function paint() {
  const [summary, approvals, companies] = await Promise.all([
    get('/api/summary'),
    get('/api/approvals'),
    get('/api/companies'),
  ]);

  // On a detail route this is the record being shown; elsewhere it is null.
  // The shell resolves it, so no module parses the hash a second time.
  const { id } = currentRoute();
  const focused = id ? companies.find((c) => c.id === id) : null;

  // The rail's only count, and it is a count that NEEDS the operator — never
  // a total (docs/design/06-components.md, "Nav item badge"). It stays the
  // PLATFORM's count even inside one company: the rail is furniture, and
  // furniture that changed meaning per route would be unlearnable.
  navCount('approvals', approvals.length);

  const tiles = region('tiles');
  if (tiles) tiles.innerHTML = tileRow(summary, approvals, companies);

  // One approvals region, declared by three panes and filled in at most one
  // (docs/design/12-application-shell.md, "the regions contract"). A company
  // workspace sees only its own; every other route sees the whole queue.
  //
  // Skipped entirely while an approval payload is being edited: a repaint that
  // deletes half-typed text in a request someone is about to authorise is a
  // defect, not a refresh.
  const asks = region('asks');
  if (asks && !editing()) {
    // A route addressing a company the roster does not have has no subject to
    // scope a queue to, and the pane already says so. Rendering "Nothing needs
    // you right now" from here would make a claim about the whole platform out
    // of a filter that matched nothing — false the moment a different company
    // is waiting.
    const orphan = id && !focused;
    const shown = id ? approvals.filter((a) => a.company_id === id) : approvals;
    asks.innerHTML = orphan ? '' : asksRegion(shown, focused ? focused.name : null);
  }

  const cos = region('companies');
  if (cos) {
    cos.innerHTML = companies.length
      ? companies.map(coCard).join('')
      : `<div class="empty"><p>No companies yet</p>
         <span>Use <b>New company</b> up top to create your first one — it starts running
         straight away, and asks before doing anything that spends money.</span>
         <div class="empty__act">
           <button class="btn btn--primary" data-act="open-new">New company</button></div></div>`;
  }

  // The company workspace pays for its own fetch, and only when it is the
  // active route — the same bargain paintSettings already makes.
  if (id && region('company-head')) {
    await paintCompany(id, approvals.filter((a) => a.company_id === id));
  }
}

function paintAll() {
  paint();
  paintHealth();
  paintNotes();
  paintSettings();
}

registerApprovalActions();
registerCompanyActions();
registerSystemActions();
registerNewCoActions();

setRefresh(paintAll);
startDispatch();
startPanel();
startShell(paintAll);

paintAll();
setInterval(paintAll, 15000);
