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


TREND = pathlib.Path("jarvis/api/static/app/trend.js")
WORKSPACE = pathlib.Path("jarvis/api/static/app/company-workspace.js")


def test_a_trend_line_is_never_drawn_through_a_single_point() -> None:
    """docs/design/06-components.md, `.trend` rule 1 — the reason the component
    was reserved from M8-2 to M9-2 rather than approximated.

    This is not a defensive edge case: it is the shape of ALL the live data.
    Every real KPI series on the platform holds exactly one reading (M9-F72),
    so a `<polyline>` emitted without the two-point guard would put an invented
    line on every goal on every company page — `01-principles.md` #3's defect
    with a chart drawn around it, and one that would look entirely convincing.

    Pinned structurally because the guard is one `? :` away from being deleted
    by someone tidying, and no other check in the suite renders this component.
    """
    source = TREND.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"//.*", "", source)

    polylines = [m.start() for m in re.finditer(r"<polyline", source)]
    assert len(polylines) == 1, (
        f"expected exactly one <polyline> emission in trend.js, found {len(polylines)}"
    )
    guard = source.find("values.length > 1")
    assert guard != -1, (
        "the two-point guard is gone from trend.js — a single reading would be "
        "drawn as a line (docs/design/06-components.md, `.trend` rule 1)"
    )
    assert guard < polylines[0], (
        "the <polyline> is emitted before the two-point guard, so it is not guarded by it"
    )


def test_the_trend_is_drawn_in_ink_and_spends_no_status_colour() -> None:
    """docs/design/02-color.md rule 2, "one meaning per surface".

    On a company page colour already means health. A series stroked in
    `--status-healthy` when it is meeting its target would put a second meaning
    on colour beside the meter that owns the first, and would restate as a hue
    a judgement `health_parts` already gives as a number — while quietly
    duplicating the direction-aware attainment maths in CSS, of all places.

    The rule is cheap to state and easy to lose to one plausible-looking line,
    so it is asserted over the component's own declarations.
    """
    css = COMPONENTS.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    blocks = re.findall(r"(\.trend[^{]*)\{([^}]*)\}", css)
    assert blocks, "no .trend rules found in components.css"
    for selector, body in blocks:
        spent = re.findall(r"var\(\s*(--(?:status|wash|accent|meter)[a-z-]*)", body)
        assert not spent, (
            f"{selector.strip()} spends a status colour ({spent}); the trend is "
            "drawn in ink — docs/design/02-color.md, 'one meaning per surface'"
        )


def test_the_trend_chart_is_hidden_from_assistive_tech_and_says_it_in_words() -> None:
    """docs/design/09-accessibility.md, "colour is never the only channel",
    applied to a component that uses no colour at all.

    The drawing carries movement; a screen reader and a greyscale screenshot
    both get that movement from `.trend__note` instead. So the `<svg>` is
    `aria-hidden` — announcing it would be noise, not information — and the
    note is the thing that must never be dropped. Both halves are asserted,
    because either one alone is a silent accessibility regression.
    """
    source = TREND.read_text(encoding="utf-8")
    assert 'aria-hidden="true"' in source, (
        "the trend <svg> must be aria-hidden — its content is announced as the "
        "note beneath it, not as a graphic"
    )
    assert "trend__note" in source, (
        "the trend lost its prose line, which is the accessible equivalent of "
        "the chart rather than a caption for it"
    )


def test_the_series_is_not_refetched_on_every_repaint() -> None:
    """docs/design/13-company-workspace.md, "Fetching the series without paying
    for it every cycle" (M9-F26).

    This page already runs the most expensive poll on the surface every 15
    seconds. The series read is behind a freshness key and a visibility check;
    dropping either turns a cached read into a second unconditional per-company
    fetch on every cycle, which nothing user-visible would reveal — the page
    would look identical and simply cost twice as much.
    """
    source = WORKSPACE.read_text(encoding="utf-8")
    # Comments legitimately name the route they explain; only real call sites
    # count, the same strip the §12.5 gate applies to find operator copy.
    code = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", " ", source, flags=re.S))
    calls = re.findall(r"kpi-series", code)
    assert len(calls) == 1, (
        f"the kpi-series read appears {len(calls)} times; it belongs in one place, behind the cache"
    )
    assert "freshnessKey" in source, (
        "the series freshness key is gone — the cache can no longer tell when a "
        "new reading could exist, so it is either stale forever or refetching"
    )
    assert "visibilityState" in source, (
        "the visibility check is gone — a hidden tab nobody is reading would "
        "refetch the series on every cycle"
    )


def test_the_at_risk_band_word_does_not_reuse_the_stuck_section_heading() -> None:
    """M9-F28 — the workspace's `BAND_WORDS` finalized.

    `BAND_WORDS.at_risk` used to read "needs attention", the exact text of the
    unrelated "Needs attention" heading `stuckSection` puts over `stuck[]`
    (design 13-company-workspace.md's own section name). A company can be
    `at_risk` with nothing stuck at all, so the Health tile borrowing that
    heading's words reads as if it were pointing at that section — reusing a
    heading with no way to promise it applies. Pinned so it does not drift
    back once the placeholder-copy comment it used to carry is gone.
    """
    source = WORKSPACE.read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", " ", source, flags=re.S))
    band_words = code[code.index("const BAND_WORDS") : code.index("const BAND_WORDS") + 200]
    assert "needs attention" not in band_words.lower(), (
        "BAND_WORDS.at_risk has drifted back to the stuck-section's own heading text"
    )
    assert "in trouble" in band_words, "BAND_WORDS.at_risk lost its finalized wording"
    # The heading itself is untouched — this pins the collision is gone without
    # touching the design-sanctioned section name.
    assert code.count("Needs attention") == 1, (
        "the stuck-work heading should be the only place this exact phrase appears"
    )


FORMAT = pathlib.Path("jarvis/api/static/app/format.js")


def test_a_sub_unit_reading_is_not_rounded_away_to_zero() -> None:
    """M9-F101 — `measurement()` against its own stated contract.

    Its docstring has promised significant-figure rounding since M9-3; the code
    did `toFixed(2)` and round-tripped through `Number()`, so **0.0005 became
    "0"**. The reading that motivated the function was the one it erased, and it
    erased it into the single value a measurement must never be confused with:
    `10-interaction-patterns.md` is explicit that zero is a measurement, so
    rendering "very nearly zero" as `0` is a lie of format in the same family as
    rendering "unmeasured" as `0`.

    Pinned at the source, because there is no JavaScript runner in this repo and
    the arithmetic therefore has no executable test (recorded as M9-F103). What
    is asserted is the *mechanism*: places derived from the magnitude, and the
    fixed-decimal shape that caused the defect gone.
    """
    source = FORMAT.read_text(encoding="utf-8")
    body = source[source.index("export function measurement") :]

    assert "Math.log10" in body, (
        "measurement() no longer derives its precision from the magnitude — a "
        "fixed decimal count rounds a sub-unit reading away to '0' (M9-F101)"
    )
    assert "< 1 ? 2 :" not in body, (
        "the fixed-decimal shape is back: toFixed(2) renders 0.0005 as '0.00', "
        "which Number() then collapses to '0'"
    )
    assert "if (x === 0) return '0'" in body, (
        "a true zero must still render '0' — it is a measurement, and the fix "
        "for M9-F101 must not turn it into something else"
    )


def test_the_trend_note_states_the_relation_and_knows_which_way_is_good() -> None:
    """M9-F100 — the Phase-3 gate's finding.

    The chart drew Data freshness (0.0005 against a 24-hour ceiling — excellent)
    and Reports delivered (3 against a goal of 4 — short) as the *identical*
    mark: a dot below a line. It had to. The y axis is value space, and value
    space does not know which way is good — `direction: "below"` means lower is
    better (M7-F30), so "below the line" is a triumph for one metric and a
    shortfall for the next.

    Only words can carry that, and because the `<svg>` is `aria-hidden` they
    were also the only channel a screen reader ever had. Both halves of the gap
    close in the same sentence, which is why the direction check and the note
    are asserted together rather than apart.
    """
    source = TREND.read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", " ", source, flags=re.S))

    for phrase in ("on target", "ahead of target", "short of target"):
        assert phrase in code, f"the trend note lost its {phrase!r} relation"
    assert "direction === 'below'" in code, (
        "the relation is no longer direction-aware — a lower-is-better metric "
        "sitting comfortably under its ceiling would read as short of target (M7-F30)"
    )
    note = code.index("function note(")
    assert "relation(" in code[note:], (
        "the relation is computed but never reaches the note, which is the only "
        "channel a screen reader has for it"
    )


def test_the_trend_relation_never_leaves_a_dangling_pronoun() -> None:
    """M9-F104 — the copy pass's antecedent fix.

    `relation()`'s shortfall branch used to return "short of it": read on its
    own — which is exactly how it is read, since the note is one paragraph and
    the word "target" never otherwise appears in it — "it" has no antecedent.
    "on target" and "ahead of target" both name the noun outright; the third
    branch has to as well, or the sentence a screen reader hears is missing its
    subject.
    """
    source = TREND.read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", " ", source, flags=re.S))
    assert "short of it" not in code, (
        "the dangling-pronoun relation is back — every branch of relation() "
        "must name 'target' so the phrase stands alone (M9-F104)"
    )


def test_the_pending_update_marker_never_renders_without_a_served_field() -> None:
    """docs/design/06-components.md, `.co-card__update` (M9-F27, gate-ruled).

    Lit at M9-1d: `/api/companies` now carries a presence-only `pending_update`
    boolean from a cheap existence check (`PlatformKernel.has_pending_update`),
    so the marker is no longer dormant. What this test still pins is the
    *shape* of the guard — the markup renders strictly from the served field,
    never from an inference — which is exactly as true now that the field is
    lit as it was while it was dormant.

    The failure this guards is specific and tempting: making the card *look*
    right by inferring a pending update from something else on the payload, or
    by fetching every company's detail to find out. Both would be a mark that
    lies, one of them expensively.
    """
    emitted = surface_text()
    assert "co-card__update" in emitted, "the pending-update marker is gone"
    assert "c.pending_update ?" in emitted, (
        "the marker is no longer guarded by the served field — it must render "
        "from `pending_update` or not at all, never from an inference"
    )

    css = COMPONENTS.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    block = re.search(r"\.co-card__update\s*\{([^}]*)\}", css)
    assert block, "no .co-card__update rule in components.css"
    assert "--accent" in block.group(1), (
        "the marker must carry the accent — an affordance, not a status"
    )
    spent = re.findall(r"var\(\s*(--(?:status|wash)[a-z-]*)", block.group(1))
    assert not spent, (
        f"the pending-update marker spends a status colour ({spent}); a template "
        "update is not a health problem and must never look like one (D-030)"
    )


TILES = pathlib.Path("jarvis/api/static/app/tiles.js")


def _tiles_source() -> str:
    source = TILES.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"//.*", "", source)


def test_the_census_tile_reads_the_served_census_not_a_client_side_filter() -> None:
    """design EXECUTIVE-LAYER.md Part 3/8, D-039 (M9-1d).

    Before this packet "Needs a look" counted `health_band !== 'healthy'`
    client-side — a filter that cannot tell a `never_measured` company apart
    from a genuinely `healthy` one, because that distinction does not exist
    on the card payload at all (D-027.4's grace period bands a young company
    `healthy`, correctly, for that company). The count must come from
    `/api/summary`'s own `census`, a direct read of `PortfolioHealth`, not a
    second, weaker aggregation invented in the browser.
    """
    source = _tiles_source()
    assert "summary.census" in source, "the tile no longer reads the served census"
    assert "health_band !== 'healthy'" not in source, (
        "the old client-side filter is back — it cannot see never_measured"
    )


def test_the_census_tile_never_computes_a_portfolio_score() -> None:
    """design Part 3's surface rule, restated: a single number covering every
    company is the one addition this packet refuses. Guards against the
    tempting shortcut of averaging `health` across `companies` for a tile
    value instead of reading the served per-band counts.

    `approvals.reduce` is the one legitimate `reduce()` in this file (finding
    the oldest pending approval) and predates this packet; any *other*
    reduce — over `companies`, in particular — is exactly the shape a
    portfolio average would take."""
    source = _tiles_source()
    reduces = re.findall(r"\b\w+(?:\.\w+)*\.reduce\(", source)
    assert reduces, "expected the existing approvals.reduce to still be here"
    assert all(call == "approvals.reduce(" for call in reduces), (
        f"unexpected reduce() call(s) in tiles.js: {reduces} — averaging comparable "
        "per-company scores is comparable to nothing (design Part 3) and must never "
        "back a tile value"
    )
    assert "/ companies.length" not in source and "/ census" not in source


def test_the_worst_company_link_is_escaped_and_never_a_second_destination() -> None:
    """The link reuses `coCard`'s own route (`companyHref`) and the card's own
    `.btn--link` in-prose affordance (docs/design/06-components.md) rather
    than inventing either — extend-first, and one destination per company,
    reached from two places rather than two links to the same place."""
    source = _tiles_source()
    assert "companyHref(worst.id)" in source
    assert 'class="btn--link"' in source
    assert "esc(worst.name)" in source
    assert "esc(worst.health_reason)" in source


def test_never_measured_is_reported_even_when_nothing_needs_a_look() -> None:
    """D-039's "one honest limitation", restated as a surface rule: a
    never-measured company is not folded into "all companies healthy" just
    because nothing is in `watch` or `at_risk` — the count must still reach
    the operator (M9-1d)."""
    source = _tiles_source()
    assert "census.never_measured" in source
    assert "needLook || census.never_measured" in source, (
        "never_measured no longer keeps the census line visible on its own — "
        "a young, unmeasured company would go silently unmentioned"
    )


def test_the_census_tile_shares_one_voice_with_the_card_for_never_measured() -> None:
    """M9-F112/F114 — census tile wording reconciled with the card.

    The card's `health_reason` for a never-measured company reads "Set goals,
    but nothing's been measured yet." (or the healthy-band twin, "Just getting
    started — nothing's been measured yet.") and the workspace drill-down says
    "Nothing measured yet" / "Not measured yet." — all three say "yet". The
    tile used to say "never measured", which reads as a verdict rather than an
    invitation and does not agree with either sibling surface. Pinned so the
    tile's count label cannot regress to the old wording independently of the
    other two, which live in different files entirely.
    """
    source = _tiles_source()
    assert "not yet measured ${census.never_measured}" in source, (
        "the census tile's label has drifted from 'not yet measured' — it must "
        "keep the same 'yet' voice as the card and the workspace drill-down"
    )
    assert "never measured ${census.never_measured}" not in source, (
        "the tile is back to 'never measured', out of voice with the card's "
        "'nothing's been measured yet' and the drill-down's 'measured yet' (M9-F112/F114)"
    )


def test_the_spending_paused_reason_is_escaped_before_it_reaches_the_tile() -> None:
    """`platform_feed`'s first reader (design Part 8, M9-F2): the halt
    narrative is live Decision Log prose laundered through
    `render_operator_text` server-side, but it is still an API value, and the
    tile's own escaping contract (`tiles.js`'s module comment) applies to it
    exactly as it does to every other context-line value."""
    source = _tiles_source()
    assert re.search(r"esc\(\s*summary\.spending_paused_reason", source), (
        "spending_paused_reason reaches the tile without going through esc() — "
        "an unescaped API value in a context string is a hole (tiles.js's own rule)"
    )
