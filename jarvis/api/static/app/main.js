// Composition root for the operator surface.
//
// This module owns start-up and the repaint cycle; every other module owns one
// region and knows nothing about the others. Nothing here builds markup.

import { get } from './api.js';
import { startDispatch } from './actions.js';
import { startPanel } from './panel.js';
import { setRefresh } from './refresh.js';
import { tileRow } from './tiles.js';
import { askCard, editing, registerApprovalActions } from './approvals.js';
import { coCard, registerCompanyActions } from './companies.js';
import { paintHealth, paintNotes, registerSystemActions } from './system.js';
import { registerNewCoActions } from './newco.js';

const el = (id) => document.getElementById(id);

async function paint() {
  const [summary, approvals, companies] = await Promise.all([
    get('/api/summary'),
    get('/api/approvals'),
    get('/api/companies'),
  ]);

  el('tiles').innerHTML = tileRow(summary, approvals, companies);

  // The page's centre of gravity moves. When something needs the operator it
  // takes the top and is loud; when nothing does it collapses to one quiet line
  // and the companies become the hero.
  //
  // The region is skipped entirely while an approval payload is being edited:
  // a repaint that deletes half-typed text in a request someone is about to
  // authorise is a defect, not a refresh.
  if (!editing()) {
    el('asks').innerHTML = approvals.length
      ? `<h2 class="section-head section-head--urgent">Needs your OK
           <span class="section-head__count">${approvals.length}</span></h2>` +
        approvals.map(askCard).join('')
      : `<h2 class="section-head">Needs your OK</h2>
         <p class="calm">Nothing needs you right now.</p>`;
  }

  el('cos').innerHTML = companies.length
    ? companies.map(coCard).join('')
    : `<div class="empty"><p>No companies yet</p>
       <span>Use <b>New company</b> up top to create your first one — it starts running
       straight away, and asks before doing anything that spends money.</span>
       <div style="margin-top:16px">
         <button class="btn btn--primary" data-act="open-new">New company</button></div></div>`;
}

function paintAll() {
  paint();
  paintHealth();
  paintNotes();
}

registerApprovalActions();
registerCompanyActions();
registerSystemActions();
registerNewCoActions();

setRefresh(paintAll);
startDispatch();
startPanel();

paintAll();
setInterval(paintAll, 15000);
