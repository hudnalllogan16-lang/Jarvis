"""Plain-language rendering of approvals and failures (spec §12.5).

§12.5 requires approval prompts in plain operator language, "generated fresh per
request — never a raw dump of technical parameters", and gives the shape:
"Trading Fund wants to buy 50 shares of NVIDIA (~$X). Approve?"

Rendering is deterministic string assembly over the structured fields, not model
generation. The operator sees language, but the numbers in that language are the
stored values — so what they read is what they authorise.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from decimal import Decimal

from jarvis.approvals.models import ApprovalRequest

TECHNICAL_TERMS = frozenset(
    {
        "workflow",
        "dag",
        "agent",
        "worker",
        "capability",
        "prompt",
        "token",
        "wake cycle",
        "temporal",
        "event bus",
        "orchestration",
        "credential scope",
        "retry",
        "dead-letter",
        "dead letter",
        "business",
        "m6",
        "m7",
        "m8",
        "kpi",
    }
)
"""Concepts §12.5 forbids in the default UI. Used to assert, not to filter —
stripping them would hide a caller writing operator text in the wrong register.

`business` was added carrying the runtime-guard follow-up from the M6 product
re-review: D-007's own translation table requires Business -> Company, so the
raw word is exactly as forbidden here as `workflow` or `retry` are — it had
simply never been listed.

`m6`/`m7`/`m8` and `kpi` were added for M7-F50 (packet M7-5a item 4): live
Manager prose reached the operator feed echoing internal framing ("the M7
targets"), and D-027.2 makes `KPI` a name this codebase uses for itself, not a
word an owner was ever taught. Word-boundary only, deliberately narrow to the
three milestone codenames in play rather than a general "m-then-a-number"
pattern — the next milestone gets its own entry when it is actually reached,
not a speculative one now (§14).

This guard sits only on `render_operator_text`'s path (live Decision Log and
notification prose) — MODEL prose, per the packet. It must never reach
`compliance_requirements`: those are owner-approved stored values, four of
which begin "During M7" by design (D-027.5, DECISIONS.md correction F-C), and
are read only by the planning prompt (`jarvis/manager/activities.py`), never
by this renderer. Laundering the owner's own rules on a surface that quotes
them verbatim would be the opposite of D-011."""

_MORPHOLOGICAL_VARIANTS: dict[str, tuple[str, ...]] = {
    "workflow": ("workflow", "workflows"),
    "dag": ("dag", "dags"),
    "agent": ("agent", "agents"),
    "worker": ("worker", "workers"),
    "capability": ("capability", "capabilities"),
    "prompt": ("prompt", "prompts", "prompted", "prompting"),
    "token": ("token", "tokens"),
    # "wake cycle" found live (M6 product re-review, runtime term coverage)
    # passing through as "woken" -- a plain substring/phrase check for "wake
    # cycle" never matches a wholly different word derived from the same
    # concept. "waking" is added as the same kind of gap before it is found
    # live rather than after. Bare "wake"/"wakes" were left out at first on
    # the argument that they collide with ordinary English ("wake up", "in
    # the wake of") that Manager-authored prose is not stretching to use
    # technically -- reversed at M9-9 (product REVISE item 4): the argument
    # was never "these forms are safe", only "no live failure demonstrated
    # otherwise" yet, and a Manager narrating its own schedule has every
    # reason to reach for the bare word ("it will wake again tomorrow")
    # without ever saying "cycle" or an inflection this table already caught.
    # Ordinary-English collisions remain the risk they always were; the
    # judgment call is that leaking the platform's own scheduling vocabulary
    # into an operator's feed is the worse failure of the two.
    "wake cycle": ("wake cycle", "wake cycles", "woken", "waking", "wake", "wakes"),
    "temporal": ("temporal",),
    "event bus": ("event bus", "event buses"),
    "orchestration": ("orchestration", "orchestrated", "orchestrating"),
    "credential scope": ("credential scope", "credential scopes"),
    "retry": ("retry", "retries", "retrying", "retried"),
    "dead-letter": ("dead-letter", "dead-letters"),
    "dead letter": ("dead letter", "dead letters"),
    # D-007: Business -> Company. "businesslike"/"businesswoman" etc. do not
    # match: word-boundary matching requires a non-word character on both
    # sides, so the word has to stand alone the way "company" would.
    "business": ("business", "businesses"),
    # M7-F50 (packet M7-5a item 4): milestone codenames, matched as their own
    # word so a real word merely containing the letter-digit pair (there are
    # none in ordinary English) is not a risk worth guarding against — unlike
    # "wake"/"woken", nothing here needed a second form.
    "m6": ("m6",),
    "m7": ("m7",),
    "m8": ("m8",),
    "kpi": ("kpi", "kpis"),
}
"""Word-boundary variants per forbidden concept (runtime term coverage,
M6 product re-review). A naive substring check (`term in text`) already
catches most plurals and inflections by accident (`"retry" in "retrying"`),
but a real word-boundary match does not get that accident for free -- it has
to be told about "workers", "capabilities", "retrying" explicitly, the same
way it has to be told that "woken" is a form of "wake cycle" rather than a
different word. Enumerated rather than stemmed: a stemmer would also decide
silently whether e.g. "businesslike" stems to "business", and that decision
belongs in this reviewed list, not in a library's heuristics."""

_TECHNICAL_TERM_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(
        re.escape(variant) for variants in _MORPHOLOGICAL_VARIANTS.values() for variant in variants
    )
    + r")\b",
    re.IGNORECASE,
)


def format_money(amount: Decimal) -> str:
    """Format an amount for display, e.g. ``$1,250.00``."""
    return f"${amount:,.2f}"


def render_request(request: ApprovalRequest, company_name: str) -> str:
    """Render the one-line ask an operator sees first.

    Args:
        request: The approval request.
        company_name: Operator-facing company name (spec §12.5: Business →
            Company).

    Returns:
        A single sentence naming the company, the action, and the amount.
    """
    parts = [f"{company_name} wants to {request.action_summary.rstrip('.')}"]
    if request.amount_usd is not None:
        parts.append(f" ({format_money(request.amount_usd)})")
    if request.counterparty:
        parts.append(f" with {request.counterparty}")
    return "".join(parts) + "."


def render_detail(request: ApprovalRequest, company_name: str) -> dict[str, str]:
    """Render the four facts spec §8 requires the approval UI to display.

    Returns:
        Mapping of operator-facing label to value. Labels are questions rather
        than field names because the operator is deciding, not reading a record.
    """
    detail = {
        "What happens": render_request(request, company_name),
        "Why now": request.triggering_condition,
        "What could go wrong": request.downside,
    }
    if request.amount_usd is not None:
        detail["How much"] = format_money(request.amount_usd)
    return detail


PAYLOAD_LABELS: dict[str, str] = {
    "title": "Title",
    "body": "What it says",
}
"""Effect-parameter key -> operator-facing label.

The keys are the tool's own parameter contract (D-024.1), so this table is
platform-controlled vocabulary rather than anything a model or an operator can
introduce. A key with no entry falls back to its own name in sentence case,
which is the honest failure: an unlabelled field is still shown in full rather
than hidden because nobody named it."""

PAYLOAD_ORDER: tuple[str, ...] = ("title", "body")
"""Reading order for the labelled keys. Everything else follows, sorted, so the
same stored payload always renders in the same order — two operators looking at
one approval must be looking at the same thing."""


def render_payload(parameters: Mapping[str, object]) -> list[dict[str, str]]:
    """Render the effect payload an approval authorises, for reading (§8, D-011).

    Since D-024.1 an approved action carries the *actual bytes* the effect will
    publish, composed by the platform from stored capability output. Those bytes
    were derived from untrusted external content, and until this existed the
    operator approved them without ever seeing them: the approval surface showed
    the four §8 facts and nothing of the payload. Rendering them is what makes
    §8's "display the specific action" true of what actually happens rather than
    of a summary of it.

    Deterministic assembly over stored values, exactly like `render_detail` —
    nothing here re-asks a model what the payload says, because a model's
    account of attacker-influenced bytes is not the bytes.

    Args:
        parameters: The approval's stored parameters.

    Returns:
        One entry per field, in a stable order, each carrying the storage key
        (so a correction can be sent back under the right name), an operator
        label, and the **whole** value as text. Never truncated: a teaser is a
        payload the operator did not read.
    """
    known = [key for key in PAYLOAD_ORDER if key in parameters]
    rest = sorted(key for key in parameters if key not in PAYLOAD_ORDER)
    return [
        {"key": key, "label": _payload_label(key), "value": _payload_text(parameters[key])}
        for key in [*known, *rest]
    ]


def payload_is_correctable(parameters: Mapping[str, object]) -> bool:
    """Return whether the operator may edit this payload before approving (A-003).

    True only when every stored value is text. A correction has to round-trip
    through the operator's screen and come back as the *same* structure it left
    as; a number or a nested object edited as a string would return as a
    different type, and `approve` would read that type change as a correction the
    operator never made. So a payload that cannot round-trip is shown read-only
    rather than edited approximately — visible either way, which is what §8
    requires; editable only where the edit means exactly what it looks like.
    """
    return bool(parameters) and all(isinstance(value, str) for value in parameters.values())


def _payload_label(key: str) -> str:
    """Return the operator-facing label for one payload key."""
    labelled = PAYLOAD_LABELS.get(key)
    if labelled is not None:
        return labelled
    spelled = key.replace("_", " ").strip()
    return spelled[:1].upper() + spelled[1:] if spelled else "Detail"


def _payload_text(value: object) -> str:
    """Render one stored payload value as text, whole and deterministically."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool | int | float | Decimal):
        return str(value)
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def render_failure(company_name: str, what_failed: str) -> str:
    """Render a failure in plain consequence language (spec §12.5).

    §12.5's own example: "Affiliate Business couldn't publish today's post —
    retrying", never "Job failed: retry 2/3, error: RATE_LIMIT_EXCEEDED".
    """
    return f"{company_name} couldn't {what_failed.rstrip('.')} — Jarvis is trying again."


def contains_technical_language(text: str) -> bool:
    """Return whether ``text`` uses a concept §12.5 bars from the default UI.

    Used in tests as an executable check on §12.5 rather than a review habit.

    Matches whole words/phrases via `_TECHNICAL_TERM_PATTERN` rather than a
    plain substring test. Two live failures showed a substring test was not
    enough: it happens to catch some inflections for free ("retry" inside
    "retrying") but not others ("worker" is not inside "workers", and "woken"
    is not inside "wake cycle" at all — a different word for the same
    concept). A word-boundary match also closes the false-positive side of
    the same gap for free: "woken" no longer matches inside "awoken", because
    a real word boundary requires a non-word character on both sides and
    "awoken" has none between its "a" and "woken".
    """
    return _TECHNICAL_TERM_PATTERN.search(text) is not None
