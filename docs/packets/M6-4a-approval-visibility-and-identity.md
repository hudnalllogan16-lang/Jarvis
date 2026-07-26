## Packet M6-4a: the operator sees what they authorize; activities assert derived identity

**Agent:** security-engineer   **Model:** opus — §8/D-011 human-authority surface and the
D-002 identity boundary; both audit findings sit exactly where a mistake authorizes the wrong
thing.

**Part 1 — surface the effect payload (M6-4 audit finding 1)**
`jarvis/api/app.py` (approval routes) returns only rendered request/detail text; `parameters`
— since D-024.1 the actual bytes to be published (title/body composed from capability output
that read untrusted external content) — are never shown, and the dashboard renders only
`a.detail`. Fix:
- The approval detail response includes the effect payload, rendered for reading (plain
  labels, §12.5; the full payload visible, not a teaser).
- The dashboard approval card exposes it (collapsed/expandable is fine; invisible is not).
- A correction affordance exists end to end: the operator can edit the payload before
  approving; the edit lands as `modified_parameters` (A-003) and resets the graduation streak
  (D-010 — a test must prove the streak resets through the API path).
- Graduation guard: confirm by test that `affiliate.publish_post` cannot graduate off
  approvals decided before payload visibility existed (check what the counter currently holds
  in the live DB and state it in the report; if any streak progress predates this packet,
  reset it via the real correction/reset mechanism and audit the reset — not by raw UPDATE).

**Part 2 — D-002 assertion in Manager activities (M6-4 audit finding 2)**
`ManagerActivities` never derives identity; `execute_approved_action` trusts
`row.business_id` from a payload-selected approval id. Add the assertion:
`RuntimeIdentity.from_activity().business_id == row.business_id`, mismatches denied and
audited (the M6-F21 bus-scoping stays as defense in depth, not the only defense). Generalize:
every ManagerActivities path where a payload-carried id reaches a contract, credential, or
effect gets the same derived-identity check. Tests include the negative control (a mismatched
workflow identity is refused and audited).

**Acceptance criteria**
- [ ] `bash scripts/gates.sh` → exit 0; test count before → after
- [ ] Approval detail (API + dashboard markup) shows the payload; §12.5 static gate green
- [ ] Correction path proven: API-level modify → `modified_parameters` stored → D-010 streak
      reset → executed effect uses the corrected bytes (D-024.1 extended: corrected values are
      still stored values)
- [ ] Identity assertion in place with audited deny + negative-control test
- [ ] Report: live vs simulated; state of the live graduation counters

**Out of scope**
The M6-5a operator-surface REVISE items (separate packet — coordinate by not touching
`index.html` beyond the approval card region). Notification lifecycle. Decision-log rendering.

**Escalate instead of deciding if**
- Payload rendering can't avoid model prose without a new rendering mechanism (D-011 question)
- The correction affordance requires changing what `approve` means (D-006/A-003 semantics)
- Any existing approval row can't be made visible-compatible without a migration
