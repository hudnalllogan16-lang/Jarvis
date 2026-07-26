#!/usr/bin/env python3
"""Query run manifests. Answers operational questions without spending context.

Every question below is one the Engineering Manager would otherwise answer by
re-reading old reports — which spends exactly the resource the delegation
architecture exists to protect. Ask the tool instead.

    python3 scripts/runlog.py summary
    python3 scripts/runlog.py gates          # which gates fail or degrade most
    python3 scripts/runlog.py rework         # which packets needed retries
    python3 scripts/runlog.py workers        # per-worker rework rate
    python3 scripts/runlog.py touched jarvis/manager   # who last changed a path
    python3 scripts/runlog.py escalations

A note on the worker questions: dispatch data is coordinator-declared, not
observed (see scripts/manifest.py). Rework counts are therefore only as reliable
as the coordinator's report. Gate outcomes and changed files are observed and can
be trusted. The tool labels which is which rather than presenting them as equals,
because a rework statistic that silently mixes the two would be used to judge a
worker on the basis of an unverified claim.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

MANIFEST_DIR = pathlib.Path("docs/runs")


def load() -> list[dict]:
    """Load every manifest, oldest first."""
    if not MANIFEST_DIR.exists():
        return []
    out = []
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            print(f"  (skipped unreadable manifest: {path})", file=sys.stderr)
    return sorted(out, key=lambda m: m.get("generated_at", ""))


def cmd_summary(runs: list[dict]) -> None:
    """One line per run."""
    if not runs:
        print("No runs recorded yet.")
        return
    print(f"{'RUN':<14} {'STATUS':<11} {'PACKETS':<9} {'RETRIES':<8} ESCALATIONS")
    for m in runs:
        d = m.get("declared", {})
        print(
            f"{m['run']:<14} {m['status']:<11} "
            f"{len(d.get('packets', [])):<9} "
            f"{sum(d.get('retries', {}).values()):<8} "
            f"{d.get('escalations', 0)}"
        )


def cmd_gates(runs: list[dict]) -> None:
    """Which gates fail or degrade most often. Observed data."""
    fails: collections.Counter[str] = collections.Counter()
    degrades: collections.Counter[str] = collections.Counter()
    total = 0
    for m in runs:
        gates = m.get("observed", {}).get("gates", {})
        total += 1
        fails.update(gates.get("failed", []))
        degrades.update(gates.get("degraded", []))

    print(f"[observed] across {total} run(s)\n")
    if not fails and not degrades:
        print("  No gate failures or degradations recorded.")
        return
    for name, count in fails.most_common():
        print(f"  FAILED    {name:<16} {count}x")
    for name, count in degrades.most_common():
        print(f"  DEGRADED  {name:<16} {count}x  (could not run — not a defect)")


def cmd_rework(runs: list[dict]) -> None:
    """Which packets needed retries. Coordinator-declared."""
    print("[coordinator-declared — as reliable as the coordinator's report]\n")
    any_found = False
    for m in runs:
        retries = m.get("declared", {}).get("retries", {})
        for packet, count in sorted(retries.items()):
            if count:
                any_found = True
                worker = (
                    m.get("declared", {}).get("dispatch", {}).get(packet, {}).get("worker", "?")
                )
                unit = "retry" if count == 1 else "retries"
                print(f"  {m['run']:<12} {packet:<14} {count} {unit}  ({worker})")
    if not any_found:
        print("  No retries recorded.")


def cmd_workers(runs: list[dict]) -> None:
    """Per-worker packet and retry counts. Coordinator-declared."""
    packets: collections.Counter[str] = collections.Counter()
    retries: collections.Counter[str] = collections.Counter()
    for m in runs:
        d = m.get("declared", {})
        dispatch = d.get("dispatch", {})
        for packet, info in dispatch.items():
            worker = info.get("worker", "?")
            packets[worker] += 1
            retries[worker] += d.get("retries", {}).get(packet, 0)

    if not packets:
        print("No dispatch data recorded yet.")
        return
    print("[coordinator-declared]\n")
    print(f"{'WORKER':<28} {'PACKETS':<9} {'RETRIES':<9} RATE")
    for worker, count in packets.most_common():
        rate = retries[worker] / count if count else 0
        flag = "  <-- review packet clarity" if rate >= 1 else ""
        print(f"{worker:<28} {count:<9} {retries[worker]:<9} {rate:.2f}{flag}")
    print(
        "\nA high rate usually means packets to that worker are underspecified,\n"
        "not that the worker is weak. Check the packets before the agent prompt."
    )


def cmd_touched(runs: list[dict], prefix: str) -> None:
    """Which runs changed files under a path. Observed for files, declared for who."""
    print(f"[files observed · attribution coordinator-declared]\n\nUnder {prefix}:\n")
    found = False
    for m in reversed(runs):
        observed = m.get("observed", {})
        hits = [
            f
            for f in observed.get("files_changed", []) + observed.get("files_added", [])
            if f.startswith(prefix)
        ]
        if hits:
            found = True
            workers = sorted(
                {i.get("worker", "?") for i in m.get("declared", {}).get("dispatch", {}).values()}
            )
            print(f"  {m['run']:<12} {len(hits)} file(s)  workers: {', '.join(workers) or '?'}")
            for f in hits[:8]:
                print(f"      {f}")
            if len(hits) > 8:
                print(f"      ... and {len(hits) - 8} more")
    if not found:
        print("  No recorded run changed files under that path.")


def cmd_escalations(runs: list[dict]) -> None:
    """Which runs escalated."""
    hits = [m for m in runs if m.get("declared", {}).get("escalations", 0)]
    if not hits:
        print("No escalations recorded.")
        return
    for m in hits:
        count = m["declared"]["escalations"]
        print(f"  {m['run']:<12} {count} escalation(s)  status={m['status']}")
    print("\nEscalation text lives in the coordinator's report, not the manifest —")
    print("escalations pass to the Manager verbatim and are not summarised into data.")


def main() -> int:
    """Dispatch a subcommand."""
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    command, rest = sys.argv[1], sys.argv[2:]
    runs = load()

    handlers = {
        "summary": lambda: cmd_summary(runs),
        "gates": lambda: cmd_gates(runs),
        "rework": lambda: cmd_rework(runs),
        "workers": lambda: cmd_workers(runs),
        "escalations": lambda: cmd_escalations(runs),
        "touched": lambda: cmd_touched(runs, rest[0] if rest else "jarvis/"),
    }
    handler = handlers.get(command)
    if handler is None:
        print(f"Unknown command: {command}\n")
        print(__doc__)
        return 1
    handler()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
