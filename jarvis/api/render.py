"""Operator-facing rendering of live Decision Log prose (spec §12.5, §11.5).

`approvals/rendering.py` renders approvals from *structured stored values*
(D-011) — there is never free text to clean because there is no free text.
The Decision Log is different: §11.5 makes it the Manager's own narrative, so
its `summary`/`rationale` fields are prose a model wrote, not fields assembled
from a template. A live cycle's synthesis can lean on its own working
vocabulary — an approval id it is tracking, the raw lifecycle word a status
change used, a word from §12.5's forbidden list — and none of that belongs in
front of an operator.

None of it is fixed by editing stored rows, either: the Decision Log is
append-only (A-006) and a "cleaned" row would no longer be the entry the
Manager actually wrote, which defeats §11.5's forensic purpose. So the
boundary is enforced here, at render time, on every read, rather than once at
write time — the same "at the boundary, not in stored data" shape
`jarvis/api/app.py`'s module docstring already claims for the rest of this
package.
"""

from __future__ import annotations

import re

from jarvis.approvals.rendering import contains_technical_language
from jarvis.domain.lifecycle import OPERATOR_LABELS, LifecycleState

_ID_PATTERN = re.compile(r"\b(?:apr|biz|cyc|dec|inv|evt|ntf)_[0-9a-f]{6,}\b", re.IGNORECASE)
"""Platform-minted identifiers (`jarvis.kernel.ids._new_id`: `<prefix>_<hex>`).
An internal reference leaking into a sentence, not a value anyone approved —
contrast D-011, where the numbers *in* an approval's rendered text are exactly
what the operator is meant to see. Matched by prefix rather than one pattern
per id kind, so a future id shape is still caught."""

_ID_REPLACEMENT = "something"

_RAW_LIFECYCLE_WORDS: dict[str, str] = {
    word: OPERATOR_LABELS[state]
    for state in LifecycleState
    for word in (state.value, state.value.upper())
}
_LIFECYCLE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in _RAW_LIFECYCLE_WORDS) + r")\b"
)
"""Raw lifecycle values (`provisioning`, `ACTIVE`, ...) that occasionally reach
prose directly rather than through the D-007 translation table — found live in
M6-5a: a transition wrote "moved from provisioning to active" into the
activity feed. The write path is fixed at its source (`registry.py`); this is
the backstop for that entry and for any other prose that does the same."""

NEUTRAL_FALLBACK = "Working — details inside."
"""Shown when a summary still reads as technical after id-stripping and
lifecycle translation. Never the raw prose with the flagged word cut out: a
partially-redacted sentence is still unreviewed model prose, and §12.5 asks
for plain language, not laundered jargon. The full text remains one click away
in "Full details" (§12.5's drill-down, unaffected by this guard)."""

DOING_NOW_LIMIT = 140
"""Character budget for the company card's one-line "Doing now" (spec §12.5:
one sentence in the default view). The drill-down activity feed keeps the
full text — this limit applies only to the card."""


def _strip_ids(text: str) -> str:
    return _ID_PATTERN.sub(_ID_REPLACEMENT, text)


def _translate_lifecycle_words(text: str) -> str:
    return _LIFECYCLE_PATTERN.sub(lambda m: _RAW_LIFECYCLE_WORDS[m.group(1)], text)


def render_operator_text(raw: str) -> str:
    """Render one piece of live Decision Log prose for the operator surface.

    Args:
        raw: The stored `summary` or `rationale`, written by a Manager cycle.

    Returns:
        Text safe for the default view: platform ids removed, raw lifecycle
        words translated (D-007), and — if the result still contains a §12.5
        forbidden concept — replaced outright with :data:`NEUTRAL_FALLBACK`
        rather than shown with the offending word cut out.
    """
    cleaned = _translate_lifecycle_words(_strip_ids(raw))
    if contains_technical_language(cleaned):
        return NEUTRAL_FALLBACK
    return cleaned


def render_doing_now(raw: str) -> str:
    """Render the company card's one-line "Doing now" summary.

    Applies :func:`render_operator_text` and then caps the result to
    :data:`DOING_NOW_LIMIT` characters with an ellipsis — the card is the
    default view, not the drill-down, and §12.5 keeps the default view to one
    sentence. Callers that need the full text (the activity feed) should call
    :func:`render_operator_text` directly instead.
    """
    text = render_operator_text(raw)
    if len(text) <= DOING_NOW_LIMIT:
        return text
    return text[:DOING_NOW_LIMIT].rstrip() + "…"


__all__ = ["DOING_NOW_LIMIT", "NEUTRAL_FALLBACK", "render_doing_now", "render_operator_text"]
