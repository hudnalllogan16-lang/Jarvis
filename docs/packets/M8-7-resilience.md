## Packet M8-7: the resilience ledger (D-034, all four points)

**Agent:** workflow-engineer   **Model:** opus — workflow shape + ledger + scheduler under
two replay fixtures and the D-033 versioning discipline (this packet's changes to live paths
ship behind patches — its first real consumer). Finding range: **M8-F85–F99**.
Lane: `lane/m8-7`.

**Objective:** implement D-034's four numbered policies exactly (quoted in DECISIONS.md —
binding): (1) context-load failure parks recorded and surfaced, never dies, never loops hot;
(2) deterministic cycle key (run id + cycle ordinal) so retries share the budget scope —
observed live as M7-F25's three $0.16 reservations for one logical cycle; (3) the
reservation reconcile (scheduler-owned, terminality-first, age-bound backstop, every release
audited); (4) credential refusals audited via the D-025 independent-commit path.

**Constraints:** D-033 discipline — any live-path workflow change behind a `PATCH_*` id with
per-fixture replay proof; determinism gate green; D-021/D-022 semantics unchanged beyond the
recorded amendments; SQLite/throwaway tests + the Postgres-marked lane where independent
commits need proving (D-025.2); live DB read-only. $0.

**Acceptance:** gates exit 0; tests before → after; each policy has its negative control
(park state reachable and visible; retried plan shares one scope — ledger rows prove it;
orphan reconciled and audited; refusal row survives its exception). Report 400/600.

**Escalate if** the deterministic cycle key can't coexist with D-021's plan_cycle minting
without a contract change, or the reconcile needs scheduler restructuring.
