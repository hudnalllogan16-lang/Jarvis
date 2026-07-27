"""Milestone layering invariant (docs/DEPENDENCIES.md).

A package may import only from its own milestone or earlier. Two composition
roots are exempt, because wiring the graph means importing all of it.

Tested rather than reviewed because the failure mode is gradual: one forward
import in a service module passes review unnoticed, and a few months later the
layering is gone with no single commit to blame. This turns "we intend to keep
these layered" into something that fails a build.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MILESTONE: dict[str, int] = {
    # M1 — Platform Kernel
    "kernel": 1,
    "domain": 1,
    "registry": 1,
    "observability": 1,
    "persistence": 1,
    "llm": 1,
    # M2 — execution spine
    "events": 2,
    "budget": 2,
    "capabilities": 2,
    "security": 2,
    "runtime": 2,
    # M3 — operator surface
    "approvals": 3,
    "notifications": 3,
    "kpi": 3,
    "api": 3,
    # M4 — Manager runtime
    "manager": 4,
    "scheduler": 4,
    # M5 — activation path
    "businesses": 5,
    "shell": 5,
}

COMPOSITION_ROOTS = {
    pathlib.Path("jarvis/kernel/container.py"),
    pathlib.Path("jarvis/runtime/worker.py"),
    pathlib.Path("jarvis/shell/launcher.py"),
    pathlib.Path("jarvis/__main__.py"),
}
"""Exempt: these construct the object graph rather than sitting in it.

`__main__.py` is a three-line delegation to the launcher — an entrypoint by
definition. The launcher was added deliberately as the third root (roadmap revision 3): it
composes the development topology — API + worker + scheduler in one process —
and holds no logic of its own. `test_composition_roots_hold_no_logic` keeps
that claim honest.
"""

SOURCES = sorted(pathlib.Path("jarvis").rglob("*.py"))


def _package_of(path: pathlib.Path) -> str:
    parts = path.relative_to("jarvis").parts
    return parts[0] if len(parts) > 1 else "kernel"


def read_source(path: pathlib.Path) -> str:
    """Return a source file's text, always decoded as UTF-8.

    Explicit because `Path.read_text()` uses the platform default, which on a
    Windows cp1252 locale cannot decode every byte a UTF-8 source may contain
    — a curly double quote in one docstring raised `UnicodeDecodeError` here
    and took gate 2 with it, since `scripts/gates.sh` imports this module's
    `_forward_imports`. A structural gate that fails for a reason unrelated
    to the property it checks is worse than one that does not run, because it
    reads as a layering violation. `tests/surface_sources.py` already reads
    every source as UTF-8 for exactly this reason.
    """
    return path.read_text(encoding="utf-8")


def _forward_imports(path: pathlib.Path) -> set[str]:
    """Return packages this file imports from a later milestone."""
    milestone = MILESTONE.get(_package_of(path))
    if milestone is None:
        return set()
    out: set[str] = set()
    for node in ast.walk(ast.parse(read_source(path))):
        if isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.startswith("jarvis."):
                continue
            target = node.module.split(".")[1]
            if MILESTONE.get(target, 0) > milestone:
                out.add(target)
    return out


@pytest.mark.parametrize("path", SOURCES, ids=str)
def test_no_forward_imports_outside_composition_roots(path: pathlib.Path) -> None:
    """A package imports only its own milestone or earlier."""
    if path in COMPOSITION_ROOTS:
        return
    forward = _forward_imports(path)
    assert not forward, (
        f"{path} imports from a later milestone: {sorted(forward)}. "
        "Either the dependency is real — in which case update docs/DEPENDENCIES.md "
        "and move the milestone — or it belongs behind a composition root."
    )


def test_composition_roots_still_exist() -> None:
    """An exemption for a deleted file silently widens the invariant."""
    for root in COMPOSITION_ROOTS:
        assert root.exists(), f"{root} is exempt but missing; remove the exemption"


def test_composition_roots_are_the_only_exemptions_needed() -> None:
    """Guards against the exemption list quietly growing.

    If a third file needs to import forward, that is a design decision worth
    making deliberately rather than by adding a path to a set.
    """
    offenders = {p for p in SOURCES if p not in COMPOSITION_ROOTS and _forward_imports(p)}
    assert offenders == set()


def test_every_package_has_a_milestone() -> None:
    """An unassigned package is exempt from the invariant by accident."""
    packages = {_package_of(p) for p in SOURCES if len(p.relative_to("jarvis").parts) > 1}
    assert packages <= set(MILESTONE), f"unassigned: {sorted(packages - set(MILESTONE))}"


def test_documented_milestones_match_the_code() -> None:
    """Keeps the table in docs/DEPENDENCIES.md honest about what exists."""
    doc = read_source(pathlib.Path("docs/DEPENDENCIES.md"))
    for package in MILESTONE:
        assert f"`{package}`" in doc, f"{package} is missing from the layering table"


ENTRYPOINT_ROOTS = {
    pathlib.Path("jarvis/shell/launcher.py"),
    pathlib.Path("jarvis/__main__.py"),
}
"""Roots that only *start* things. `container.py` legitimately defines the DI
container class and `worker.py` hosts run loops; the entrypoints, by contrast,
must stay free of behaviour — a launcher that grows classes is a service being
written in the wrong file."""


def test_entrypoint_roots_hold_no_logic() -> None:
    """The launcher and __main__ wire and start; they must not define classes."""
    import ast as _ast

    for root in ENTRYPOINT_ROOTS:
        tree = _ast.parse(read_source(root))
        classes = [n.name for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef)]
        assert not classes, f"{root} defines {classes}; move behaviour into a component"
