#!/usr/bin/env python3
"""Assemble a run manifest from execution facts (not from anyone's account of them).

A run manifest is the durable, machine-readable record of one coordinator run. It
exists so the Engineering Manager can answer operational questions — which gates
fail most often, which packets needed rework, which milestones escalated — without
re-reading natural-language reports, and so that operational history stops
competing with architecture for space in the Manager's context.

**Why this is a script and not something the coordinator writes.**

The coordinator has no Write tool, deliberately, and it must not gain one here. A
manifest the coordinator authored would be a self-report: exactly the thing the
coordinator itself is instructed not to trust when a worker claims its gates
passed. Structured self-reports are worse than prose ones, because structure reads
as authority — a JSON file saying `"status": "success"` invites belief in a way a
paragraph does not.

So the manifest separates two zones, and labels them:

* ``observed`` — derived from artifacts the coordinator cannot forge: gate records
  written by ``scripts/gates.sh`` at the moment each gate ran, and git's own view
  of what changed on disk. If the suite failed, no manifest can say it passed.
* ``declared`` — the coordinator's account of what it dispatched: which packet went
  to which worker on which model. This is a claim, and it is marked as one. It is
  worth recording because nothing else knows it, and it is the answer to "which
  worker last touched this subsystem" — but a reader should know its trust level
  differs from the gate results sitting next to it.

That distinction is the same one this project applies everywhere else: verified by
execution versus written down (see finding M5-F5, and the report format in
``docs/DELEGATION.md``).

Usage:
    python3 scripts/manifest.py --run M6 \\
        --packets M6-0,M6-1,M6-2 \\
        --dispatch '{"M6-0":["test-engineer","sonnet"],"M6-1":["business-type-author","sonnet"]}' \\
        --retries '{"M6-1":1}' \\
        --escalations 0
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from datetime import UTC, datetime

RECORD_DIR = pathlib.Path(".jarvis-run")
MANIFEST_DIR = pathlib.Path("docs/runs")
SCHEMA_VERSION = 1


def _git(*args: str) -> str:
    """Run a git command, returning empty string if git is unavailable."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv
            ["git", *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect_gate_records() -> list[dict[str, object]]:
    """Read every gate record emitted since the last manifest was written.

    Each record was written by ``scripts/gates.sh`` at the moment a gate ran.
    Corrupt records are skipped rather than failing the assembly: a manifest with
    one unreadable record is more useful than no manifest.
    """
    if not RECORD_DIR.exists():
        return []
    records: list[dict[str, object]] = []
    for path in sorted(RECORD_DIR.glob("gate-*.json")):
        try:
            records.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def summarise_gates(records: list[dict[str, object]]) -> dict[str, object]:
    """Reduce gate records to per-gate outcomes and an overall status.

    Worst-outcome-wins per gate: a gate that failed once in a run is reported as
    failed even if a later retry passed, because the run *did* fail a gate and
    hiding that would defeat the "which gates fail most often" question.
    Retry-and-recover is visible in ``retries``, which is where it belongs.
    """
    severity = {"passed": 0, "degraded": 1, "failed": 2}
    outcomes: dict[str, str] = {}
    for record in records:
        for gate in record.get("gates", []):  # type: ignore[union-attr]
            name, status = str(gate["name"]), str(gate["status"])
            if severity.get(status, 0) >= severity.get(outcomes.get(name, "passed"), 0):
                outcomes[name] = status

    final_exit = int(records[-1].get("exit_code", -1)) if records else -1
    tests = next((str(r.get("tests")) for r in reversed(records) if r.get("tests")), "")

    return {
        "passed": sorted(n for n, s in outcomes.items() if s == "passed"),
        "degraded": sorted(n for n, s in outcomes.items() if s == "degraded"),
        "failed": sorted(n for n, s in outcomes.items() if s == "failed"),
        "final_exit_code": final_exit,
        "runs": len(records),
        "tests": tests,
    }


def overall_status(gates: dict[str, object], escalations: int) -> str:
    """Derive run status from observed facts only.

    Never "success" while a gate failed or an escalation is open, regardless of
    what any report says. Degraded is its own status because a degraded run has
    not verified anything and must not be mistaken for a pass.
    """
    if escalations:
        return "escalated"
    if gates["failed"]:
        return "failed"
    if gates["degraded"]:
        return "degraded"
    if gates["passed"] and gates["final_exit_code"] == 0:
        return "success"
    return "unknown"


def build(args: argparse.Namespace) -> dict[str, object]:
    """Assemble the manifest."""
    records = collect_gate_records()
    gates = summarise_gates(records)
    dispatch: dict[str, list[str]] = json.loads(args.dispatch) if args.dispatch else {}
    retries: dict[str, int] = json.loads(args.retries) if args.retries else {}

    changed = [line for line in _git("diff", "--name-only", "HEAD").splitlines() if line]
    untracked = [
        line
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line and not line.startswith(".jarvis-run/")
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "run": args.run,
        "status": overall_status(gates, args.escalations),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "observed": {
            "_provenance": (
                "Derived from gate records written by scripts/gates.sh as each gate "
                "ran, and from git. Cannot be authored by a coordinator or worker."
            ),
            "gates": gates,
            "files_changed": sorted(changed),
            "files_added": sorted(untracked),
            "commit": _git("rev-parse", "--short", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        },
        "declared": {
            "_provenance": (
                "Reported by the delivery coordinator. This is a claim about what was "
                "dispatched, not a verified outcome. Trust it accordingly."
            ),
            "packets": args.packets.split(",") if args.packets else [],
            "dispatch": {
                packet: {"worker": pair[0], "model": pair[1] if len(pair) > 1 else "unknown"}
                for packet, pair in dispatch.items()
            },
            "retries": retries,
            "escalations": args.escalations,
        },
        "artifacts": {
            "gate_records": str(RECORD_DIR),
            "manifest": f"{MANIFEST_DIR}/{args.run}.json",
        },
    }


def main() -> int:
    """Write the manifest and clear the consumed gate records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="Run id, e.g. M6 or M6-hotfix")
    parser.add_argument("--packets", default="", help="Comma-separated packet ids")
    parser.add_argument("--dispatch", default="", help='JSON {"packet":["worker","model"]}')
    parser.add_argument("--retries", default="", help='JSON {"packet":count}')
    parser.add_argument("--escalations", type=int, default=0)
    parser.add_argument(
        "--keep-records",
        action="store_true",
        help="Don't clear gate records after assembly (useful when debugging)",
    )
    args = parser.parse_args()

    manifest = build(args)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    out = MANIFEST_DIR / f"{args.run}.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")

    if not args.keep_records:
        # Consumed records are cleared so the next run's manifest describes that
        # run rather than accumulating every gate ever executed.
        for path in RECORD_DIR.glob("gate-*.json"):
            path.unlink(missing_ok=True)

    gates = manifest["observed"]["gates"]  # type: ignore[index]
    print(f"{out}: status={manifest['status']} gates={gates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
