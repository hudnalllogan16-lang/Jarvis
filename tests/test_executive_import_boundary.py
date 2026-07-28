"""Executive Layer import boundary (design EXECUTIVE-LAYER.md Part 1, D-038).

D-038: the deterministic Executive package computes and reports; it never
writes to a contract. The property that keeps that honest is an import rule
rather than a docstring promise — design Part 1: "the executive package
imports registry, budget, kpi, observability and notifications, and nothing
else... In particular it does not import jarvis.llm, jarvis.manager, or
jarvis.capabilities." Importing `jarvis.llm` from this package **is** the
event "someone crossed the deterministic/judgment line"; `jarvis.manager` and
`jarvis.capabilities` are the two packages business internals are reachable
through (design Part 1).

`tests/test_layering.py` already keeps `executive` (M9, the last milestone) from
importing nothing forward — every other package is "earlier" by definition.
That is exactly why this needs its own test: `llm` (M1), `manager` (M4), and
`capabilities` (M2) are all earlier than M9 and would pass the ordinary
layering check cleanly while still crossing the one boundary D-038 draws.
"""

from __future__ import annotations

import ast
import pathlib

EXECUTIVE_SOURCES = sorted(pathlib.Path("jarvis/executive").rglob("*.py"))

FORBIDDEN_ROOTS = frozenset({"llm", "manager", "capabilities"})
"""The two packages business internals are reachable through, plus the one
package that spends money on a model call (design Part 1)."""

ALLOWED_ROOTS = frozenset(
    {"registry", "budget", "kpi", "observability", "notifications", "kernel", "domain"}
)
"""D-038's five, plus `kernel` and `domain` — the milestone-1 primitives (typed
ids, errors, the Standard Business Contract, the lifecycle enum) that every one
of the five permitted packages already depends on themselves. Excluding them
here would not narrow what the Executive can reach — `registry.get_contract`
already returns a `BusinessContract` on every permitted call — it would only
make this package's own function signatures untyped."""


def _imported_roots(source: str) -> set[str]:
    """Return every top-level ``jarvis.<root>`` package a source string imports.

    Takes source text rather than a path so the negative-control tests below
    can exercise it against a synthetic violation that names no real file.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "jarvis":
                roots.update(alias.name for alias in node.names)
            elif node.module.startswith("jarvis."):
                roots.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("jarvis."):
                    roots.add(alias.name.split(".")[1])
    return roots


def test_the_package_has_source_to_check() -> None:
    """A suite with nothing to scan would pass every check below vacuously."""
    assert EXECUTIVE_SOURCES, "jarvis/executive/ has no source files"


def test_executive_never_imports_the_judgment_or_business_internal_packages() -> None:
    """The literal violation event design Part 1 names.

    `llm`, `manager`, and `capabilities` are all earlier milestones than
    `executive` and so pass `tests/test_layering.py` cleanly — this is the
    check that actually catches a model call or a reach into business
    internals landing in this package.
    """
    offenders = {
        str(path): sorted(_imported_roots(path.read_text(encoding="utf-8")) & FORBIDDEN_ROOTS)
        for path in EXECUTIVE_SOURCES
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"forbidden imports in the deterministic Executive package: {offenders}"


def test_executive_imports_only_the_five_plus_foundational_types() -> None:
    """The stronger form of D-038: not just excluding three, including only these.

    A future package added to the platform and imported here without a
    milestone conversation would pass `test_layering.py` (if its milestone is
    <= 9, which every existing milestone is) and slip past the test above (if
    it is not one of the three named packages) — this is the one that catches
    that.
    """
    offenders = {
        str(path): sorted(_imported_roots(path.read_text(encoding="utf-8")) - ALLOWED_ROOTS)
        for path in EXECUTIVE_SOURCES
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"import outside D-038's frozen surface: {offenders}"


def test_the_detector_detects() -> None:
    """Negative control: prove the AST walk actually flags a violation.

    M8-F120's discipline: a gate that has never failed is indistinguishable
    from a gate that cannot fail. Runs `_imported_roots` on synthetic source
    naming each forbidden package in a different import form and asserts every
    one is caught — the packet's own instruction that "the test proves the
    detector detects".
    """
    synthetic = """
from jarvis.llm.base import CompletionRequest
from jarvis.manager.workflow import BusinessManager
import jarvis.capabilities.pool
from jarvis import llm as also_llm
"""
    found = _imported_roots(synthetic)
    assert found & FORBIDDEN_ROOTS == FORBIDDEN_ROOTS, (
        f"the detector missed a synthetic violation: found {sorted(found)}, expected all of "
        f"{sorted(FORBIDDEN_ROOTS)} — the boundary test would be vacuous."
    )
    assert (found - ALLOWED_ROOTS) == FORBIDDEN_ROOTS


def test_a_permitted_import_is_not_flagged() -> None:
    """The other half of the negative control: the detector is not trigger-happy.

    A detector that flagged every import would also "detect" the synthetic
    violation above — proving it fires is only meaningful alongside proof that
    it stays quiet on the reads design Part 1 actually permits.
    """
    synthetic = """
from jarvis.registry.registry import BusinessRegistry
from jarvis.budget.ledger import BudgetLedger
from jarvis.kpi.engine import KpiEngine
from jarvis.observability.decision_log import DecisionLog
from jarvis.notifications.service import NotificationService
from jarvis.kernel.ids import BusinessId
from jarvis.domain.lifecycle import LifecycleState
"""
    found = _imported_roots(synthetic)
    assert found & FORBIDDEN_ROOTS == set()
    assert found - ALLOWED_ROOTS == set()
