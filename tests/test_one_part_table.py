"""The part table is written down exactly once (M10-F19, design 1.3, packet P0-A).

The runtime audit's central fact was three composition roots that each wrote
their own part list. The list *is* the topology; it existed three times, nothing
asserted the three agreed, and they did not — invisibly, until an operator ran
the wrong one. No single commit was to blame, which is the same failure shape
`test_layering.py`'s docstring describes for forward imports and the same answer:
turn the convention into something that fails a build.

`Supervisor.add` was already called from exactly one module when this test was
written. That is precisely when the guard is worth adding — a fifth entrypoint
may exist, a second opinion about what runs may not.
"""

from __future__ import annotations

import ast
import pathlib

from tests.test_layering import read_source

SOURCES = sorted(pathlib.Path("jarvis").rglob("*.py"))

PART_TABLE = pathlib.Path("jarvis/shell/service.py")
"""The one module allowed to compose the supervised runtime."""


def _supervisor_names(tree: ast.AST) -> set[str]:
    """Return the local names in `tree` that hold a Supervisor.

    Two ways a module can get one, and both must count or the detector has a
    hole the size of a helper function: constructing it (`s = Supervisor()`)
    and being handed it (`def add_parts(s: Supervisor)`).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            called = ast.unparse(node.value.func).split(".")[-1]
            if called == "Supervisor":
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotation = ast.unparse(node.annotation).split(".")[-1].strip("\"'")
            if annotation == "Supervisor":
                names.add(node.arg)
    return names


def _adds_parts(source: str) -> bool:
    """Return whether `source` registers a part on a Supervisor."""
    tree = ast.parse(source)
    holders = _supervisor_names(tree)
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in holders
        for node in ast.walk(tree)
    )


def test_one_part_table() -> None:
    """Exactly one module in `jarvis/` calls `Supervisor.add`.

    The gate that would have caught the three-topology divergence at the commit
    that created it.
    """
    composers = {path for path in SOURCES if _adds_parts(read_source(path))}
    assert composers == {PART_TABLE}, (
        f"the supervised part table is composed in {sorted(str(p) for p in composers)}. "
        "It is written down exactly once: every entrypoint is a choice of which face to "
        f"put on {PART_TABLE}'s set of parts, never a second opinion about what the set is."
    )


def test_the_detector_fires_on_a_second_part_table() -> None:
    """The detector detects — otherwise the test above passes vacuously.

    Both routes into a Supervisor are covered, because a second topology
    written as a helper taking one as an argument is exactly the shape that
    would slip past a constructor-only scan.
    """
    constructed = """
from jarvis.shell.supervisor import Supervisor

def build():
    other = Supervisor()
    other.add("worker", "Company runner", lambda: None)
    return other
"""
    injected = """
from jarvis.shell.supervisor import Supervisor

def extend(sup: Supervisor) -> None:
    sup.add("extra", "Something else", lambda: None)
"""
    assert _adds_parts(constructed)
    assert _adds_parts(injected)


def test_the_detector_is_not_trigger_happy() -> None:
    """`.add` on anything that is not a Supervisor is not a part table."""
    unrelated = """
def widen(values: set[str]) -> None:
    values.add("worker")
"""
    assert not _adds_parts(unrelated)


def test_the_service_never_reaches_for_a_window() -> None:
    """`jarvis-run` is headless by construction, not by intention (design 1.2).

    The service has no window whose close event can end it and never opens a
    browser. The way that stays true is that the module holding the headless
    entrypoint does not import the module that opens windows.
    """
    tree = ast.parse(read_source(PART_TABLE))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any("desktop" in name or "webbrowser" in name for name in imported), (
        f"{PART_TABLE} imports a window or browser module: {sorted(imported)}"
    )


def test_the_declared_entrypoints_resolve() -> None:
    """`pyproject.toml`'s console scripts name callables that exist.

    A typo here is invisible until an operator installs the package and runs a
    command that does not exist — and the whole point of this packet is that
    `jarvis-run` is the command every deployment mode runs.
    """
    import importlib

    declared = dict(
        line.split("=", 1)
        for line in read_source(pathlib.Path("pyproject.toml"))
        .split("[project.scripts]", 1)[1]
        .split("[", 1)[0]
        .strip()
        .splitlines()
    )
    targets = {name.strip(): value.strip().strip('"') for name, value in declared.items()}
    assert targets == {
        "jarvis": "jarvis.shell.launcher:main",
        "jarvis-run": "jarvis.shell.service:serve_headless",
    }
    for target in targets.values():
        module_name, _, attribute = target.partition(":")
        assert callable(getattr(importlib.import_module(module_name), attribute))
