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
    }
)
"""Concepts §12.5 forbids in the default UI. Used to assert, not to filter —
stripping them would hide a caller writing operator text in the wrong register."""


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
    """
    lowered = text.lower()
    return any(term in lowered for term in TECHNICAL_TERMS)
