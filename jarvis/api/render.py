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

_ID_ONLY_PAREN_PATTERN = re.compile(
    r"\s?\((?:\s*\b(?:apr|biz|cyc|dec|inv|evt|ntf)_[0-9a-f]{6,}\b\s*[,;]?\s*)+\)",
    re.IGNORECASE,
)
"""A parenthetical whose *entire* content is one or more platform ids (M6
product re-review F2, carried into M7-2: "a pending approval (something)"
read as a bug — found live as "An approval request
(apr_1a161be0303c4cf5910e51e50c7d6775) is pending review."). The parenthetical
existed only to name the id; once the id is gone it is a vestigial pair of
parens around a placeholder, not information. Dropped whole, together with
the leading space, so the sentence reads as prose rather than a redaction.
A parenthetical that mixes an id with other words (e.g. "(see apr_1a2b3c4d)")
is left to the plain `_ID_PATTERN` substitution below — there the parens are
doing other work and removing them would delete real content."""

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

NEUTRAL_FALLBACK = "Details inside."
"""Shown when a summary still reads as technical after id-stripping and
lifecycle translation. Never the raw prose with the flagged word cut out: a
partially-redacted sentence is still unreviewed model prose, and §12.5 asks
for plain language, not laundered jargon. The full text remains one click away
in "Full details" (§12.5's drill-down, unaffected by this guard).

Was "Working — details inside." (M9-3 surface backlog, M9-F44): this text renders through two
callers with different tenses — the card's one-line "Latest update"
(present-moment, where "Working" fit) and the activity feed's own entries
(each one a past, timestamped event, where "Working" claimed the company was
still doing something a completed entry does not support). A guard shared by
both call sites cannot assert either tense, so it now asserts neither."""

DOING_NOW_LIMIT = 140
"""Character budget for the company card's one-line "Latest update" (spec
§12.5: one sentence in the default view). The drill-down activity feed keeps
the full text — this limit applies only to the card."""


def _strip_ids(text: str) -> str:
    text = _ID_ONLY_PAREN_PATTERN.sub("", text)
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
    """Render the company card's one-line "Latest update" summary.

    Applies :func:`render_operator_text` and then caps the result to
    :data:`DOING_NOW_LIMIT` characters with an ellipsis — the card is the
    default view, not the drill-down, and §12.5 keeps the default view to one
    sentence. Callers that need the full text (the activity feed) should call
    :func:`render_operator_text` directly instead.

    The cut backs up to the last word boundary at or before the limit (M7
    product re-review F3: a plain character-count cut could land mid-word,
    e.g. truncating "...spent the aftern…" out of "afternoon"). A single
    "word" longer than the whole budget — no space to back up to — falls back
    to a hard cut rather than returning nothing.
    """
    text = render_operator_text(raw)
    if len(text) <= DOING_NOW_LIMIT:
        return text
    truncated = text[:DOING_NOW_LIMIT]
    boundary = truncated.rfind(" ")
    if boundary > 0:
        truncated = truncated[:boundary]
    return truncated.rstrip() + "…"


__all__ = ["DOING_NOW_LIMIT", "NEUTRAL_FALLBACK", "render_doing_now", "render_operator_text"]
