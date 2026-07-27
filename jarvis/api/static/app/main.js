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
import { startShell, region, navCount } from './shell.js';
import { setRefresh } from './refresh.js';
import { tileRow } from './tiles.js';
import { askCard, editing, registerApprovalActions } from './approvals.js';
import { coCard, registerCompanyActions } from './companies.js';
import { paintHealth, paintNotes, paintSettings, registerSystemActions } from './system.js';
import { registerNewCoActions } from './newco.js';

async function paint() {
  const [summary, approvals, companies] = await Promise.all([
    get('/api/summary'),
    get('/api/approvals'),
    get('/api/companies'),
  ]);

  // The rail's only count, and it is a count that NEEDS the operator — never
  // a total (docs/design/06-components.md, "Nav item badge").
  navCount('approvals', approvals.length);

  const tiles = region('tiles');
  if (tiles) tiles.innerHTML = tileRow(summary, approvals, companies);

  // The page's centre of gravity moves. When something needs the operator it
  // takes the top and is loud; when nothing does it collapses to one quiet line
  // and the companies become the hero.
  //
  // The region is skipped entirely while an approval payload is being edited:
  // a repaint that deletes half-typed text in a request someone is about to
  // authorise is a defect, not a refresh.
  const asks = region('asks');
  if (asks && !editing()) {
    asks.innerHTML = approvals.length
      ? `<h2 class="section-head section-head--urgent">Needs your OK
           <span class="section-head__count">${approvals.length}</span></h2>` +
        approvals.map(askCard).join('')
      : `<h2 class="section-head">Needs your OK</h2>
         <p class="calm">Nothing needs you right now.</p>`;
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
