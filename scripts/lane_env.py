#!/usr/bin/env python3
"""Per-lane development environments (D-026.2, implements D-025.2).

`docs/DELEGATION.md` ("Lanes, worktrees, and the merge queue") has two
implementation lanes run the full gate suite — including the `postgres`-marked
tests — against the *same* local Docker stack, at the same time. That only
works if the two lanes share no mutable state: `create <lane-id>` gives one
lane its own Postgres database, its own Temporal namespace, and its own API
port on the existing local server; `destroy <lane-id>` removes them.

Both commands refuse to go anywhere near the `jarvis` database or the
`default` Temporal namespace — those hold the live M6 evidence trail, not a
throwaway, and a lane script that could reach them by a typo is not isolation.

Usage::

    uv run python scripts/lane_env.py create t1
    uv run python scripts/lane_env.py destroy t1

`create` prints a `.env` override block to stdout; paste the four lines into
the lane worktree's `.env` (status/idempotency notes go to stderr, so stdout
stays exactly the block). Both operations are idempotent: `create` on an
already-provisioned lane reprints the same block without erroring, and
`destroy` on an absent lane succeeds silently.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import zlib
from datetime import timedelta
from urllib.parse import SplitResult, urlsplit, urlunsplit

import asyncpg
from temporalio.api.operatorservice.v1 import DeleteNamespaceRequest
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

DEFAULT_ADMIN_DATABASE_URL = "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
"""Same default as `migrations/env.py` and `Settings.database_url` — this
script and the app agree on where the local server lives unless told
otherwise. Only the host/port/credentials are used; the database name is
always replaced with the target of the operation at hand."""

DEFAULT_TEMPORAL_HOST = "localhost:7233"

ADMIN_MAINTENANCE_DATABASE = "postgres"
"""Every Postgres server has this database. `CREATE`/`DROP DATABASE` cannot
run against the database being created or dropped, so admin operations
connect here instead of to `jarvis` — which also keeps this script from ever
opening a session against the protected database at all."""

ADMIN_NAMESPACE = "default"
"""The Temporal server's own bootstrap namespace. Namespace admin RPCs
(register/delete) are issued over a client connected to *some* existing
namespace; they are not scoped to it. Using `default` for the connection is
not the same as operating *on* `default` — the guard below is what prevents
that."""

PROTECTED_DATABASE = "jarvis"
PROTECTED_NAMESPACE = "default"
"""The live M6 evidence trail (see the packet and CLAUDE.md). Never a
`create`/`destroy` target, regardless of what a lane id happens to be."""

BASE_API_PORT = 8000

LANE_ID_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
"""Lowercase alphanumeric plus internal hyphens, 1-32 chars. Restrictive on
purpose: lane ids are interpolated into SQL identifiers (`jarvis_lane_<id>`)
and Temporal namespace names (`lane-<id>`), so the charset is chosen to make
injection structurally impossible rather than merely escaped."""


class LaneEnvError(Exception):
    """Raised for refusals and unreachable services; caught once, at the top."""


def lane_database(lane_id: str) -> str:
    """Return the per-lane Postgres database name."""
    return f"jarvis_lane_{lane_id}"


def lane_namespace(lane_id: str) -> str:
    """Return the per-lane Temporal namespace name."""
    return f"lane-{lane_id}"


def lane_port(lane_id: str) -> int:
    """Return a deterministic per-lane API port.

    Derived from the lane id rather than allocated from shared state: the
    same lane id always maps to the same port, so `create` needs to talk to
    Postgres and Temporal but nothing else to pick one, and two processes
    computing it independently always agree. Collisions between different
    lane ids are possible in principle (999 slots) but are a non-issue at the
    handful of lanes M7 runs at once (docs/DELEGATION.md: 2 lanes for M7) —
    and a real collision surfaces immediately as a bind failure, not silently.
    """
    offset = 1 + (zlib.crc32(lane_id.encode("utf-8")) % 999)
    return BASE_API_PORT + offset


def _validate_lane_id(lane_id: str) -> str:
    if not LANE_ID_PATTERN.match(lane_id):
        raise LaneEnvError(
            f"invalid lane id {lane_id!r}: must be 1-32 chars of lowercase "
            "letters, digits, and internal hyphens"
        )
    return lane_id


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(SplitResult(parts.scheme, parts.netloc, f"/{database}", "", ""))


def _asyncpg_dsn(url: str) -> str:
    """Strip the SQLAlchemy driver suffix asyncpg's raw client rejects.

    `Settings.database_url` and this script's default both carry
    ``postgresql+asyncpg://...`` for SQLAlchemy's benefit; asyncpg's own
    `connect()` wants a bare ``postgresql://`` scheme and raises
    `ClientConfigurationError` on the `+asyncpg` suffix.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]
    return urlunsplit(SplitResult(scheme, parts.netloc, parts.path, "", ""))


def _default_admin_url() -> str:
    return os.environ.get("JARVIS_DATABASE_URL", DEFAULT_ADMIN_DATABASE_URL)


def _default_temporal_host() -> str:
    return os.environ.get("JARVIS_TEMPORAL_HOST", DEFAULT_TEMPORAL_HOST)


# ── Postgres ─────────────────────────────────────────────────────────────


async def _create_database(admin_url: str, lane_id: str) -> None:
    db = lane_database(lane_id)
    if db == PROTECTED_DATABASE:  # structurally unreachable given the prefix; asserted anyway
        raise LaneEnvError(f"refusing to touch the {PROTECTED_DATABASE!r} database")
    dsn = _asyncpg_dsn(_with_database(admin_url, ADMIN_MAINTENANCE_DATABASE))
    try:
        conn = await asyncpg.connect(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        raise LaneEnvError(f"Postgres unreachable at {dsn.split('@')[-1]}: {exc}") from exc
    try:
        try:
            await conn.execute(f'CREATE DATABASE "{db}"')
            print(f"  postgres: created {db}", file=sys.stderr)
        except asyncpg.exceptions.DuplicateDatabaseError:
            print(f"  postgres: {db} already exists (idempotent)", file=sys.stderr)
    finally:
        await conn.close()


async def _destroy_database(admin_url: str, lane_id: str) -> None:
    db = lane_database(lane_id)
    if db == PROTECTED_DATABASE:
        raise LaneEnvError(f"refusing to touch the {PROTECTED_DATABASE!r} database")
    dsn = _asyncpg_dsn(_with_database(admin_url, ADMIN_MAINTENANCE_DATABASE))
    try:
        conn = await asyncpg.connect(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        raise LaneEnvError(f"Postgres unreachable at {dsn.split('@')[-1]}: {exc}") from exc
    try:
        # WITH (FORCE) drops even if a lingering test session is still connected
        # to the lane database; IF EXISTS makes a repeat call a no-op.
        await conn.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        print(f"  postgres: dropped {db} (if it existed)", file=sys.stderr)
    finally:
        await conn.close()


# ── Temporal ─────────────────────────────────────────────────────────────


async def _create_namespace(temporal_host: str, lane_id: str) -> None:
    ns = lane_namespace(lane_id)
    if ns == PROTECTED_NAMESPACE:  # structurally unreachable given the prefix; asserted anyway
        raise LaneEnvError(f"refusing to touch the {PROTECTED_NAMESPACE!r} namespace")
    try:
        client = await Client.connect(temporal_host, namespace=ADMIN_NAMESPACE)
    except RuntimeError as exc:
        raise LaneEnvError(f"Temporal unreachable at {temporal_host}: {exc}") from exc
    try:
        await client.workflow_service.register_namespace(
            RegisterNamespaceRequest(
                namespace=ns,
                # The generated stub types this as `Duration | None`; a plain
                # `timedelta` is accepted and converted at the RPC boundary
                # (confirmed live: `describe_namespace` reports the resulting
                # `workflow_execution_retention_ttl` in seconds), so this is a
                # stub-vs-runtime mismatch, not a real type error.
                workflow_execution_retention_period=timedelta(days=1),  # pyright: ignore[reportArgumentType]
            )
        )
        print(f"  temporal: registered namespace {ns}", file=sys.stderr)
    except RPCError as exc:
        if exc.status == RPCStatusCode.ALREADY_EXISTS:
            print(f"  temporal: namespace {ns} already registered (idempotent)", file=sys.stderr)
        else:
            raise LaneEnvError(f"Temporal refused to register {ns}: {exc}") from exc


async def _destroy_namespace(temporal_host: str, lane_id: str) -> None:
    ns = lane_namespace(lane_id)
    if ns == PROTECTED_NAMESPACE:
        raise LaneEnvError(f"refusing to touch the {PROTECTED_NAMESPACE!r} namespace")
    try:
        client = await Client.connect(temporal_host, namespace=ADMIN_NAMESPACE)
    except RuntimeError as exc:
        raise LaneEnvError(f"Temporal unreachable at {temporal_host}: {exc}") from exc
    try:
        resp = await client.operator_service.delete_namespace(DeleteNamespaceRequest(namespace=ns))
        print(f"  temporal: deleted namespace {ns} (as {resp.deleted_namespace})", file=sys.stderr)
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            print(f"  temporal: namespace {ns} already absent (idempotent)", file=sys.stderr)
        else:
            raise LaneEnvError(f"Temporal refused to delete {ns}: {exc}") from exc


# ── CLI ──────────────────────────────────────────────────────────────────


def _env_block(admin_url: str, lane_id: str) -> str:
    lane_url = _with_database(admin_url, lane_database(lane_id))
    return "\n".join(
        [
            f"# Lane {lane_id} — paste into this worktree's .env, replacing the matching keys",
            f"JARVIS_DATABASE_URL={lane_url}",
            f"JARVIS_TEST_DATABASE_URL={lane_url}",
            f"JARVIS_TEMPORAL_NAMESPACE={lane_namespace(lane_id)}",
            f"JARVIS_API_PORT={lane_port(lane_id)}",
        ]
    )


async def _create(admin_url: str, temporal_host: str, lane_id: str) -> None:
    await _create_database(admin_url, lane_id)
    await _create_namespace(temporal_host, lane_id)
    print(_env_block(admin_url, lane_id))


async def _destroy(admin_url: str, temporal_host: str, lane_id: str) -> None:
    await _destroy_database(admin_url, lane_id)
    await _destroy_namespace(temporal_host, lane_id)
    print(f"lane {lane_id}: destroyed ({lane_database(lane_id)}, {lane_namespace(lane_id)})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lane_env.py",
        description="Provision or tear down a per-lane Postgres database, "
        "Temporal namespace, and API port (D-026.2).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Admin Postgres URL; only host/port/credentials are used "
        "(default: $JARVIS_DATABASE_URL, or the local dev default).",
    )
    parser.add_argument(
        "--temporal-host",
        default=None,
        help="Temporal frontend address (default: $JARVIS_TEMPORAL_HOST, or localhost:7233).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Provision a lane's database, namespace, and port.")
    create_p.add_argument("lane_id", help="e.g. t1, ops-1, fin-2")

    destroy_p = sub.add_parser("destroy", help="Drop a lane's database and namespace.")
    destroy_p.add_argument("lane_id", help="e.g. t1, ops-1, fin-2")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    admin_url = args.database_url or _default_admin_url()
    temporal_host = args.temporal_host or _default_temporal_host()

    try:
        lane_id = _validate_lane_id(args.lane_id)
        if args.command == "create":
            asyncio.run(_create(admin_url, temporal_host, lane_id))
        else:
            asyncio.run(_destroy(admin_url, temporal_host, lane_id))
    except LaneEnvError as exc:
        print(f"lane_env: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
