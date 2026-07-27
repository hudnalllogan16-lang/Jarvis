"""The files that carry operator-facing markup and copy, in one place.

Before M8-2 the dashboard was a single `index.html` with an inline `<style>`
and an inline `<script>`, and three separate consumers — `scripts/gates.sh`,
`tests/test_operator_language.py` and
`tests/test_approval_visibility_and_identity.py` — each re-derived "the copy an
operator can read" with their own regexes over that one file.

M8-2 decomposed the monolith into `styles/*.css` and `app/*.js`. That refactor
had one serious hazard: every one of those consumers would still have *passed*,
because a regex looking for `<script>` blocks in a file that no longer has any
finds nothing, and nothing contains no forbidden terms. The §12.5 gate would
have become a no-op without a single test turning red.

So the definition lives here, once, and every consumer imports it. The module
asserts its inputs exist and are non-empty, which is the property that makes the
silent-pass failure mode impossible: if the module set is ever emptied, renamed
or moved, the gate raises instead of vacuously passing. (Same discipline as
finding M5-F2: assert the target exists before acting on it.)

Stdlib only, and no `pytest` import: `scripts/gates.sh` runs this in a bare
interpreter with no third-party packages available.
"""

from __future__ import annotations

import pathlib
import re

STATIC = pathlib.Path("jarvis/api/static")
MARKUP = STATIC / "index.html"
SCRIPT_DIR = STATIC / "app"
STYLE_DIR = STATIC / "styles"

FORBIDDEN = [
    "workflow",
    "dag",
    "agent",
    "worker",
    "capability",
    "prompt",
    "token",
    "wake cycle",
    "woken",
    "temporal",
    "event bus",
    "orchestration",
    "credential scope",
    "retry",
    "dead-letter",
    "dead letter",
    "business",
]
"""§12.5's own list, plus two morphological gaps the runtime guard
(`jarvis.approvals.rendering.contains_technical_language`) also had to close
(M6 product re-review, runtime term coverage): "woken" is a form of "wake
cycle" a phrase check never catches, and "business" is D-007's own
Business -> Company term, never previously listed at all.

Single-sourced here (design `PLUGIN-FRAMEWORK.md` Part 6's M7-F12 note):
before this, `scripts/gates.sh` gate 2 carried its own seventeen-vs-fifteen-
term copy of this list, out of sync with `tests/test_operator_language.py`'s
— exactly the "a term the test forbids and the gate allows" gap that note
warns about. Both now import this one list, the same discipline M8-F26
already applied to *which files* carry operator-facing copy."""


def script_paths() -> list[pathlib.Path]:
    """Every behaviour module. Asserts the set is real and non-empty."""
    paths = sorted(SCRIPT_DIR.glob("*.js"))
    assert paths, (
        f"no operator-surface modules found in {SCRIPT_DIR} — the S12.5 copy gate "
        "would pass vacuously. If the modules moved, update tests/surface_sources.py."
    )
    return paths


def style_paths() -> list[pathlib.Path]:
    """Every stylesheet. Asserts the set is real and non-empty."""
    paths = sorted(STYLE_DIR.glob("*.css"))
    assert paths, f"no stylesheets found in {STYLE_DIR}"
    return paths


def markup() -> str:
    """The shipped markup shell."""
    assert MARKUP.exists(), "the operator dashboard is a S12.5 deliverable"
    return MARKUP.read_text(encoding="utf-8")


def script() -> str:
    """Every behaviour module's source, concatenated.

    Also picks up any inline `<script>` still in the markup, so the gate keeps
    working if a future change puts one back rather than silently ignoring it.
    """
    inline = "".join(re.findall(r"<script[^>]*>(.*?)</script>", markup(), flags=re.S))
    modules = "\n".join(p.read_text(encoding="utf-8") for p in script_paths())
    return inline + "\n" + modules


def surface_text() -> str:
    """Markup plus behaviour source — the blob regression pins assert against."""
    return markup() + "\n" + script()


def visible_text() -> str:
    """Only what an operator can actually read in the markup.

    Strips comments, `<style>`, `<script>` and tag internals. Developer comments
    explaining *why* a rule exists legitimately name the concepts they are
    avoiding, so counting them would make the S12.5 check unpassable for the
    right reasons. HTML comments are removed explicitly rather than left to the
    tag regex, which would leak the remainder of any comment containing a `>`.
    """
    html = markup()
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def script_literals() -> str:
    """Every string literal in the behaviour source.

    The modules build most of the visible copy, so their literals are operator
    copy and count against S12.5. Block and line comments are both stripped —
    the modules use JSDoc, which the pre-M8 line-comment-only strip would have
    missed. API paths are addresses, not copy; an operator never reads them.
    """
    source = script()
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"//.*", "", source)
    literals = " ".join(re.findall(r"['\"`]([^'\"`]{4,})['\"`]", source))
    return re.sub(r"/api/\S*", " ", literals)


__all__ = [
    "FORBIDDEN",
    "MARKUP",
    "SCRIPT_DIR",
    "STATIC",
    "STYLE_DIR",
    "markup",
    "script",
    "script_literals",
    "script_paths",
    "style_paths",
    "surface_text",
    "visible_text",
]
