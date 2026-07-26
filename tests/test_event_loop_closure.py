"""Event loop closure (spec §2, §2.1; D-006).

Written in response to a defect, not in anticipation of one. The approval
subsystem recorded an *audit* entry named ``approval.decided`` and never
published a *bus* event of that name. Every search for the name found matches,
the D-006 continuation loop looked closed, and a business that asked for
approval would have stopped permanently the moment the operator answered.

The lesson generalises: a subscription is only real if something publishes it,
and no amount of reading proves that. These tests check it mechanically.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from jarvis.events.types import ALL_EVENT_TYPES, APPROVAL_DECIDED

JARVIS = pathlib.Path("jarvis")


def _published_types() -> set[str]:
    """Return every event type reachable by a `bus.publish` call.

    Resolved through `jarvis.events.types`, which is why those constants exist:
    a literal string passed to publish would be invisible to this check.
    """
    published: set[str] = set()
    for path in JARVIS.rglob("*.py"):
        source = path.read_text()
        if "publish(" not in source:
            continue
        for name, value in _constants_referenced(source).items():
            if name in source:
                published.add(value)
    return published


def _constants_referenced(source: str) -> dict[str, str]:
    """Map imported event-type constant names to their values."""
    from jarvis.events import types as event_types

    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == "jarvis.events.types":
            for alias in node.names:
                value = getattr(event_types, alias.name, None)
                if isinstance(value, str):
                    out[alias.asname or alias.name] = value
    return out


def test_approval_decision_is_published_not_only_audited() -> None:
    """The exact defect. D-006's loop depends on this one edge."""
    assert APPROVAL_DECIDED in _published_types(), (
        "approval.decided is not published to the event bus; a Manager that "
        "raised an approval will never resume after the operator answers"
    )


def test_approval_service_holds_a_bus() -> None:
    """A structural check: the service cannot publish without one."""
    source = (JARVIS / "approvals" / "service.py").read_text()
    assert "EventBus" in source
    assert "_publish_decided" in source


def test_kernel_wires_the_bus_into_the_approval_service() -> None:
    """An optional dependency left unwired is the same bug with more steps."""
    source = (JARVIS / "kernel" / "container.py").read_text()
    assert "bus=self.build_bus(services)" in source


def test_no_module_builds_an_unwired_approval_service() -> None:
    """The kernel wiring is only worth anything if nothing bypasses it.

    Found in M6-2: the kernel wired the bus correctly and the operator API
    ignored it, constructing `ApprovalService(session, audit, decisions)` on
    the approve/deny route. `bus` defaults to None and `_publish_decided`
    returns silently, so an operator's answer was recorded, audited, written to
    the Decision Log — and no Manager was ever signalled. D-006's loop was open
    at the one place a human closes it.

    Asserting on the *call*, not on a string: the previous test proves the
    kernel passes a bus, this proves the kernel is the only builder, and
    together they leave nowhere for an unwired instance to come from.
    """
    offenders: list[str] = []
    for path in JARVIS.rglob("*.py"):
        if path == JARVIS / "kernel" / "container.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ApprovalService"
            ):
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, (
        "build the approval service through PlatformKernel.build_approvals so it "
        f"holds an event bus (D-006); constructed directly at: {offenders}"
    )


@pytest.mark.parametrize("event_type", sorted(ALL_EVENT_TYPES))
def test_declared_event_types_are_reachable(event_type: str) -> None:
    """Every declared type must be published by something.

    A type nobody publishes is a subscription that silently never fires — the
    class of defect this module exists to prevent, generalised beyond the one
    instance that caused it.
    """
    assert event_type in _published_types(), (
        f"{event_type} is declared but never published; either publish it or "
        "remove it from jarvis/events/types.py"
    )


def test_bus_event_types_are_centralised() -> None:
    """Literal event strings passed to publish would evade every check above."""
    offenders: list[str] = []
    for path in JARVIS.rglob("*.py"):
        if path.name == "types.py" and path.parent.name == "events":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "publish"
            ):
                continue
            for keyword in ast.walk(node):
                if (
                    isinstance(keyword, ast.keyword)
                    and keyword.arg == "event_type"
                    and isinstance(keyword.value, ast.Constant)
                ):
                    offenders.append(f"{path}: {keyword.value.value!r}")
    assert not offenders, (
        f"event types must come from jarvis.events.types so publication is checkable: {offenders}"
    )
