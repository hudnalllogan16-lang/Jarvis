"""Executable design-system invariants (M8-2, D-028.3).

`docs/design/` is a permanent platform artifact: future UI work extends it
rather than reinventing it. Three of its rules are mechanical properties of the
source, so they are tested rather than left to review discipline — the same
argument `test_operator_language.py` makes for §12.5.

These pin the decomposition itself. The monolith's inline `<script>`/`<style>`
made several of these failures impossible by construction; splitting the file
into modules created the room for them, so the guards arrive with the split.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tests.surface_sources import (
    STATIC,
    markup,
    script_paths,
    style_paths,
    surface_text,
)

COMPONENTS = pathlib.Path("jarvis/api/static/styles/components.css")


def test_every_asset_the_markup_references_exists() -> None:
    """The decomposition's own new failure mode.

    `index.html` now references three stylesheets and an entry module by path.
    A typo in any of them unstyles or deadens the entire surface while the
    markup still parses and the server still serves a 200 — no other check in
    the suite would notice.
    """
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', markup())
    assert refs, "the markup references no local assets — did the links move?"
    for ref in refs:
        target = pathlib.Path("jarvis/api") / ref.lstrip("/")
        assert target.exists(), f"index.html references a missing asset: {ref}"


def test_the_entry_module_is_loaded_as_a_module() -> None:
    """ES modules are the floor for this phase (M8-PLAN Part 5). Without
    `type="module"` the imports fail silently and the surface renders empty."""
    assert 'type="module"' in markup()


def test_components_reference_semantic_tokens_only() -> None:
    """docs/design/02-color.md's central rule.

    Components read tier-2 semantic tokens; the entire light/dark theme swap
    happens at that tier. A raw hex in the component layer hard-codes one theme
    and silently breaks the other — the exact defect the three-tier split
    exists to prevent, and one that no rendering test would catch because both
    themes still *render*.
    """
    css = COMPONENTS.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    leaked = re.findall(r"#[0-9A-Fa-f]{3,8}\b", css)
    assert not leaked, f"raw colour values in the component layer: {leaked}"


def test_no_inline_event_handlers_anywhere_in_the_surface() -> None:
    """docs/design/10-interaction-patterns.md, "Command and dispatch".

    All click handling goes through one delegated `[data-act]` listener. Inline
    `onclick` would force every handler to be a global — which is precisely
    what ES modules do not provide, so a reintroduced inline handler fails at
    runtime rather than at review. It would also make `<div onclick>` possible
    again, and the delegation layer exists partly to keep that impossible.
    """
    sources = {"index.html": markup()}
    for path in script_paths():
        sources[path.name] = path.read_text(encoding="utf-8")
    for name, text in sources.items():
        found = re.findall(r'\son(?:click|change|input|submit|load)\s*=\s*["\']', text)
        assert not found, f"inline event handler in {name}: {found}"


def test_reduced_motion_disables_transitions_not_only_animations() -> None:
    """Finding M8-F22: the pre-M8 rule was `*{animation:none!important}`, which
    left every transition running for a user who had explicitly asked for
    reduced motion — hover, focus and panel transitions all still fired.
    """
    base = (STATIC / "styles" / "base.css").read_text(encoding="utf-8")
    block = re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}",
        base,
        flags=re.S,
    )
    assert block, "no prefers-reduced-motion rule in the base layer"
    body = block.group(1)
    assert "animation-duration" in body
    assert "transition-duration" in body


def test_both_themes_define_the_same_semantic_tokens() -> None:
    """Light is a complete alternate, not a degraded fallback
    (docs/design/02-color.md). A token defined in one theme and missing from
    the other inherits the wrong value silently — it renders, wrongly.
    """
    tokens = (STATIC / "styles" / "tokens.css").read_text(encoding="utf-8")
    blocks = re.findall(r"\{([^{}]*)\}", tokens, flags=re.S)
    themed = [
        set(re.findall(r"(--(?:surface|text|border|status|accent|meter)-[a-z-]+)\s*:", b))
        for b in blocks
    ]
    themed = [t for t in themed if len(t) > 5]
    assert len(themed) >= 2, "expected at least two theme blocks in tokens.css"
    first = themed[0]
    for other in themed[1:]:
        assert first == other, f"theme blocks disagree on: {first ^ other}"


@pytest.mark.parametrize(
    "doc",
    [
        "README.md",
        "01-principles.md",
        "02-color.md",
        "03-typography.md",
        "04-spacing.md",
        "05-layout.md",
        "06-components.md",
        "07-iconography.md",
        "08-motion.md",
        "09-accessibility.md",
        "10-interaction-patterns.md",
        "11-persona-components.md",
    ],
)
def test_the_design_system_artifact_is_complete(doc: str) -> None:
    """D-028.3 makes `docs/design/` a permanent platform artifact carrying
    architecture-documentation weight. Deleting one of its documents should
    fail the build the way deleting a layering rule does."""
    path = pathlib.Path("docs/design") / doc
    assert path.exists(), f"missing design-system document: {doc}"
    assert len(path.read_text(encoding="utf-8")) > 500, f"{doc} is a stub"


def test_persona_components_ship_as_spec_with_no_rendering_path() -> None:
    """docs/design/11-persona-components.md: persona *data* does not exist yet,
    so rendering a persona would mean inventing one — the "decorative that
    lies" defect (docs/design/01-principles.md #3) this project has already
    paid for twice (M7-F53, M7-F60).

    The styles exist so the packet that plumbs the data has nothing left to
    invent; nothing may emit the markup until then.
    """
    styles = "\n".join(p.read_text(encoding="utf-8") for p in style_paths())
    assert "persona-chip" in styles, "the persona spec's styles should exist"
    assert "persona-chip" not in surface_text(), (
        "a persona is being rendered, but no endpoint serves persona data — "
        "see docs/design/11-persona-components.md before adding a render path"
    )
