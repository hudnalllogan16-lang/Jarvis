## Packet P0-C: the two-signal liveness verdict (OPERATIONAL-RUNTIME.md packet C)

**Agent:** platform-engineer  **Model:** sonnet — design fully specifies; gates + the
registry cover. Findings **M10-F50–F59**. Lane: `lane/p0-c`.

Implement design Part 5''s verdict half exactly: the Temporal `DescribeTaskQueue` poller
probe (external signal; UNREACHABLE renders unknown, NEVER zero); `assess_runtime_liveness`
composing heartbeat rows (P0-B''s, merged) + the probe into the verdict; the verdict as an
L1 Executive rule with the probe INJECTED (D-038 — executive imports no temporal client;
the composition root supplies the probe, mirroring the D-041 pattern); the
`runtime.liveness_verdict` registry row EXACTLY as the design drafts it (the ratchet will
rule new-surface, pin update per the P0-D precedent); the `workers` health component P0-B
deferred; transition-deduped outage notices (design: an outage is announced once with its
start, recovery once with the duration — states not alerts, D-046 family). Wire the verdict
into the executive tick after the census. Scripted harness; $0; live read-only; no service
starts; report-don''t-kill. Gates exit 0; commit "P0-C: "; never merge/push; no DECISIONS.md
edits. Report 300/450.
**Escalate if** the injected-probe seam can''t hold D-038, or verdict states need more than
the design''s enumeration.
