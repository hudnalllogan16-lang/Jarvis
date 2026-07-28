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


def test_fonts_are_linked_ahead_of_tokens() -> None:
    """M8-11 (M8-F21 closes): `fonts.css` must register the three vendored
    families before `tokens.css`'s stacks can ask for them by name — a swap
    would leave the first paint racing the stylesheet that names it."""
    refs = re.findall(r'href="(/static/[^"]+\.css)"', markup())
    assert "/static/fonts.css" in refs, "fonts.css is not linked into the page"
    assert refs.index("/static/fonts.css") < refs.index("/static/styles/tokens.css"), (
        "fonts.css must be linked ahead of tokens.css so the families are "
        "registered before anything asks for them"
    )


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
        "12-application-shell.md",
        "13-company-workspace.md",
    ],
)
def test_the_design_system_artifact_is_complete(doc: str) -> None:
    """D-028.3 makes `docs/design/` a permanent platform artifact carrying
    architecture-documentation weight. Deleting one of its documents should
    fail the build the way deleting a layering rule does."""
    path = pathlib.Path("docs/design") / doc
    assert path.exists(), f"missing design-system document: {doc}"
    assert len(path.read_text(encoding="utf-8")) > 500, f"{doc} is a stub"


SHELL = pathlib.Path("jarvis/api/static/app/shell.js")


def _rail_ids() -> set[str]:
    """The workspaces shell.js offers in the rail.

    Read from the WORKSPACES literal only: DETAIL_ROUTES follows it in the same
    file and uses the same `id:` key, so a bare file-wide scan would count a
    detail route as a rail item and make the promise below vacuous for exactly
    the entries it was extended to cover.
    """
    source = SHELL.read_text(encoding="utf-8")
    block = re.search(r"const WORKSPACES = \[(.*?)\n\];", source, flags=re.S)
    assert block, "WORKSPACES literal not found in shell.js"
    return set(re.findall(r"\bid:\s*'([a-z-]+)'", block.group(1)))


def _detail_routes() -> dict[str, str]:
    """Detail-route id -> the rail workspace it hangs off."""
    source = SHELL.read_text(encoding="utf-8")
    block = re.search(r"const DETAIL_ROUTES = \[(.*?)\];", source, flags=re.S)
    assert block, "DETAIL_ROUTES literal not found in shell.js"
    return dict(re.findall(r"id:\s*'([a-z-]+)',\s*parent:\s*'([a-z-]+)'", block.group(1)))


def test_every_nav_item_has_a_workspace_and_every_pane_is_reachable() -> None:
    """docs/design/12-application-shell.md: "a nav item is a promise that a
    destination exists".

    This is docs/design/01-principles.md #3 applied to navigation. A rail entry
    leading to an empty screen is decorative furniture that lies, and it is the
    single most tempting thing to add to a shell — the concept image names
    seven destinations and Jarvis serves data for four. The reserved three plus
    Managers are recorded in the design document, where a reservation costs the
    operator nothing; this test is what stops one drifting into the rail.

    Asserted in both directions: an orphan pane is just as wrong, because it is
    a surface the operator cannot reach.

    M9-2 widened the second direction rather than weakening it. A detail route
    (`#/companies/<id>`) is a pane the rail does not offer, so "every pane is a
    nav item" became "every pane is a nav item OR names the workspace it is
    reached from" — and a detail route whose parent is not itself in the rail is
    an orphan one level removed, which the next assertion catches.
    """
    nav_ids = _rail_ids()
    detail_ids = set(_detail_routes())
    pane_ids = set(re.findall(r'data-ws="([a-z-]+)"', markup()))
    assert nav_ids, "no workspaces found in shell.js — did WORKSPACES move?"
    reachable = nav_ids | detail_ids
    assert reachable == pane_ids, (
        f"rail and workspaces disagree: only in shell.js {reachable - pane_ids}, "
        f"only in markup {pane_ids - reachable}"
    )


def test_every_detail_route_hangs_off_a_real_workspace() -> None:
    """docs/design/12-application-shell.md, "Detail routes".

    A detail route is reached by drilling into its parent, and its parent's rail
    item stays lit while the operator is inside it. Both of those need the
    parent to exist in the rail; a detail route naming a parent that does not is
    reachable only by typing a URL, which is the orphan the rule above forbids
    wearing a different shape. The markup must declare the same parent, because
    that attribute is what the design document points a reader at.
    """
    routes = _detail_routes()
    assert routes, "no detail routes found in shell.js — did DETAIL_ROUTES move?"
    rail = _rail_ids()
    declared = dict(re.findall(r'data-ws="([a-z-]+)"\s+data-ws-parent="([a-z-]+)"', markup()))
    for pane, parent in routes.items():
        assert parent in rail, (
            f"detail route {pane!r} hangs off {parent!r}, which is not in the rail"
        )
        assert declared.get(pane) == parent, (
            f"detail pane {pane!r} declares parent {declared.get(pane)!r} in the markup "
            f"but {parent!r} in shell.js"
        )


def test_controls_that_navigate_are_links_not_buttons() -> None:
    """docs/design/12-application-shell.md, "Navigation".

    A control that navigates is a link; a control that acts is a button, and
    `[data-act]` is for the second kind only. Until M9-2 the drill into one
    company was `data-act="open-co"` on a `<button>` — which cost the operator
    middle-click, open-in-new-tab, the browser's own Back, and the status-bar
    preview of where they were about to go, all to reach what is now a route.

    Pinned because the delegated-dispatch layer makes the wrong shape the easy
    one: adding a `data-act` is one line, and nothing else in the suite would
    notice that a destination had stopped being addressable.
    """
    emitted = surface_text()
    assert "open-co" not in emitted, (
        "a company workspace is a route — reach it with an href, not an action"
    )
    assert "companyHref(" in emitted, (
        "nothing addresses a company workspace; the drill-down is unreachable"
    )
    assert 'href="#/companies/' not in emitted, (
        "the address of a company workspace is built in ONE place (companyHref). "
        "A hand-written second copy is how the card, the truncation affordance "
        "and an approval's Why? drift into three slightly different routes."
    )


def test_the_surface_makes_no_third_party_requests() -> None:
    """Finding M8-F21. Jarvis runs locally; a surface that fetches its own
    chrome from someone else's CDN is offline-fragile and tells that third
    party when the operator opened their dashboard.

    Closed at M8-4 by deleting the webfont links. The check covers CSS too:
    `@import` and `url()` are the other doors a webfont can come back through,
    and the next person to want Bricolage Grotesque will reach for one of them.
    """
    external = re.findall(r'(?:href|src)="(https?://[^"]+)"', markup())
    assert not external, f"index.html requests third-party assets: {external}"
    for path in style_paths():
        css = path.read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
        remote = re.findall(r"(?:@import|url)\s*\(?\s*['\"]?(https?://[^)'\"]+)", css)
        assert not remote, f"{path.name} requests third-party assets: {remote}"


def test_no_inline_styles_anywhere_in_the_surface() -> None:
    """The UI Phase-1 gate recorded ten inline `style=` sites in the JS
    modules, several off the 4px scale. They moved to the sheet at M8-4.

    Inline styles are not a tidiness question: a value in a template literal is
    invisible to docs/design/04-spacing.md's scale, cannot be themed, and
    cannot be found by anyone reading components.css to learn what a component
    looks like — which is the file the design system points them at.
    """
    sources = {"index.html": markup()}
    for path in script_paths():
        sources[path.name] = path.read_text(encoding="utf-8")
    offenders = {name: re.findall(r'style="[^"]*"', text) for name, text in sources.items()}
    offenders = {name: found for name, found in offenders.items() if found}
    assert not offenders, f"inline styles are a components.css concern: {offenders}"


def test_the_overlays_contain_focus_and_give_it_back() -> None:
    """Finding M8-F23 (WCAG 2.4.3), closed at M8-4.

    Behaviour is verified in a browser, not here; what this pins is that the
    sheet and the rail go through ONE implementation. They have identical
    obligations, and the reason the modal shipped without a trap in the first
    place is that focus management was nobody's single responsibility.
    """
    focus_module = pathlib.Path("jarvis/api/static/app/focus.js")
    assert focus_module.exists(), "focus containment lives in app/focus.js"
    for path in (pathlib.Path("jarvis/api/static/app/panel.js"), SHELL):
        source = path.read_text(encoding="utf-8")
        assert "trapFocus" in source, f"{path.name} opens an overlay without containing focus"


def test_the_naming_convention_migration_stayed_closed() -> None:
    """docs/design/06-components.md, "the naming convention".

    The half-migrated state (BEM elements beside flat legacy classes doing
    element work) is what let `.entry__why` be documented while `.why` shipped
    — a doc-vs-code mismatch in a system whose first rule is "extend, don't
    reinvent". These are the exact class names that were retired at M8-4.
    """
    retired = {
        "why": "entry__why / outgoing__why",
        "fld": "outgoing__field",
        "seg": "meter__seg",
        "part": "health-parts__item",
        "parts": "health-parts",
        "facts": "ask__facts",
        "fact": "ask__fact",
        "waited": "ask__waited",
    }
    emitted = surface_text()
    for name, replacement in retired.items():
        assert f'class="{name}"' not in emitted, (
            f'flat legacy class "{name}" is back — it belongs to a block now, as '
            f"{replacement} (docs/design/06-components.md, the naming convention)"
        )


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
