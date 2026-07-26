"""Pure-logic coverage for `scripts/lane_env.py` and `Settings.api_port` (D-026.2,
implements D-025.2).

Two lanes running the full gate suite at once (`docs/DELEGATION.md`, "Lanes,
worktrees, and the merge queue") depend on the parts exercised here: lane
names and ports are derived deterministically and can never collide with the
protected `jarvis` database or `default` namespace, invalid lane ids never
reach a query or an RPC, and the API port is actually configurable in both
topologies now instead of hardcoded.

What is *not* here on purpose: actually creating or dropping a database or
namespace. That was verified by hand against the Docker stack — two lane
databases and namespaces created, the `postgres`-marked tests run
concurrently against them (see the OPS-1 report for the timestamped proof of
overlap), then both destroyed with the `jarvis` DB's row counts and the
`default` namespace shown unchanged before/after. A test that mocked
asyncpg/temporalio to assert the same thing would be asserting the mock, not
the property (the M5-F5 shape); a test that ran the real thing would need the
Docker stack this suite otherwise runs without, and would fight this exact
lane workflow trying to use it for two lanes at once.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from jarvis.kernel.config import LLMSettings, Settings

_SCRIPT_PATH = pathlib.Path(__file__).parent.parent / "scripts" / "lane_env.py"
_spec = importlib.util.spec_from_file_location("lane_env", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
lane_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane_env)
"""Imported by file path rather than as a package: `scripts/` is tooling, not
a milestone package — it is deliberately absent from docs/DEPENDENCIES.md and
the layering test."""


# ── naming ───────────────────────────────────────────────────────────────


def test_lane_database_is_prefixed() -> None:
    assert lane_env.lane_database("t1") == "jarvis_lane_t1"


def test_lane_namespace_is_prefixed() -> None:
    assert lane_env.lane_namespace("t1") == "lane-t1"


@pytest.mark.parametrize("lane_id", ["t1", "t2", "ops-1", "a", "z" * 30])
def test_lane_names_can_never_equal_the_protected_names(lane_id: str) -> None:
    """No valid lane id can resolve to the live evidence DB or namespace.

    Structural, in the spirit of `test_layering.py`: the prefixes make this
    true by construction, but a refactor that dropped one "for a short name"
    would reintroduce exactly the collision the packet's escalation trigger
    exists to prevent, and this fails the moment it happens rather than the
    next time someone points a lane at `default`.
    """
    assert lane_env.lane_database(lane_id) != lane_env.PROTECTED_DATABASE
    assert lane_env.lane_namespace(lane_id) != lane_env.PROTECTED_NAMESPACE


# ── lane id validation ───────────────────────────────────────────────────


@pytest.mark.parametrize("lane_id", ["t1", "t2", "ops-1", "fin-2", "a", "a1-b2-c3"])
def test_valid_lane_ids_are_accepted(lane_id: str) -> None:
    assert lane_env._validate_lane_id(lane_id) == lane_id


@pytest.mark.parametrize(
    "lane_id",
    [
        "",
        "T1",  # uppercase
        "t_1",  # underscore
        "-t1",  # leading hyphen
        "t1-",  # trailing hyphen
        't1"; DROP DATABASE jarvis; --',
        "a" * 33,  # over the 32-char limit
    ],
    ids=[
        "empty",
        "uppercase",
        "underscore",
        "leading-hyphen",
        "trailing-hyphen",
        "sql",
        "too-long",
    ],
)
def test_invalid_lane_ids_are_refused(lane_id: str) -> None:
    """The negative control: an id built to break out of a quoted SQL
    identifier or reach past `jarvis_lane_`/`lane-` must never get as far as
    a query or an RPC. Every reject path in `create`/`destroy` runs through
    this check first."""
    with pytest.raises(lane_env.LaneEnvError):
        lane_env._validate_lane_id(lane_id)


# ── port derivation ──────────────────────────────────────────────────────


def test_lane_port_is_deterministic() -> None:
    """Two processes computing the same lane id's port must agree without
    talking to each other — there is no shared allocation table."""
    assert lane_env.lane_port("t1") == lane_env.lane_port("t1")


@pytest.mark.parametrize("lane_id", ["t1", "t2", "ops-1", "fin-2", "a", "z" * 30])
def test_lane_port_is_in_the_reserved_range(lane_id: str) -> None:
    port = lane_env.lane_port(lane_id)
    assert lane_env.BASE_API_PORT < port <= lane_env.BASE_API_PORT + 999


def test_t1_and_t2_get_different_ports() -> None:
    """The concrete pair the OPS-1 simultaneity proof actually bound at once;
    a collision here would have shown up as one of the two lanes failing to
    bind, not as a subtle test failure."""
    assert lane_env.lane_port("t1") != lane_env.lane_port("t2")


# ── URL rewriting ────────────────────────────────────────────────────────


def test_with_database_replaces_only_the_path() -> None:
    url = "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
    assert (
        lane_env._with_database(url, "jarvis_lane_t1")
        == "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis_lane_t1"
    )


def test_asyncpg_dsn_strips_the_sqlalchemy_driver_suffix() -> None:
    """asyncpg's raw `connect()` rejects the `+asyncpg` scheme SQLAlchemy
    uses (`ClientConfigurationError: invalid DSN`, confirmed live) — this is
    the fix, exercised without opening a connection."""
    url = "postgresql+asyncpg://jarvis:jarvis@localhost:5432/postgres"
    assert lane_env._asyncpg_dsn(url) == "postgresql://jarvis:jarvis@localhost:5432/postgres"


def test_asyncpg_dsn_leaves_a_plain_scheme_alone() -> None:
    url = "postgresql://jarvis:jarvis@localhost:5432/postgres"
    assert lane_env._asyncpg_dsn(url) == url


# ── the printed .env block ───────────────────────────────────────────────


def test_env_block_carries_all_four_lane_variables() -> None:
    admin_url = "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
    block = lane_env._env_block(admin_url, "t1")
    assert (
        "JARVIS_DATABASE_URL=postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis_lane_t1"
        in block
    )
    assert (
        "JARVIS_TEST_DATABASE_URL=postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis_lane_t1"
        in block
    )
    assert "JARVIS_TEMPORAL_NAMESPACE=lane-t1" in block
    assert f"JARVIS_API_PORT={lane_env.lane_port('t1')}" in block


# ── Settings.api_port (packet scope item 2) ──────────────────────────────


def test_api_port_defaults_to_8000() -> None:
    """The default must match what both topologies hardcoded before this
    packet (`jarvis/api/server.py`, `jarvis/shell/launcher.py`) — changing
    the default would move where every existing deployment's dashboard
    lives."""
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    assert settings.api_port == 8000


def test_api_port_reads_from_its_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_API_PORT", "8123")
    settings = Settings(llm=LLMSettings(model="stub-model"), _env_file=None)  # type: ignore[call-arg]
    assert settings.api_port == 8123
