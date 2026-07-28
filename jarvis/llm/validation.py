"""Startup check: is the configured model one this provider actually serves?

**Why this exists (M9-F118).** On 2026-07-28 all three companies' Managers
failed their rounds within seven seconds of each other, each on
`ProviderError: anthropic returned HTTP 404` from the planning call. Nothing was
misconfigured in the end — the trigger was a transient provider-side 404 — but
the platform had no way to tell those two cases apart, because the first thing
that ever checked the configured model against reality was the first paid
reasoning call of the first company to wake. A model id that is simply wrong
therefore presents identically to an outage: three failed rounds, retries spent,
budget reserved and released, and a diagnosis that costs a human an hour.

This moves the question to startup, where it is cheap and answerable, and says
the answer out loud.

**The posture, stated because it is the whole design.** Three verdicts, not two:

* `CONFIRMED` — the provider returned a complete list and the configured model
  is in it. Start.
* `REJECTED` — the provider returned a complete, non-empty list and the model is
  *not* in it. This is a configuration error that every future round would spend
  its retries rediscovering, so the caller refuses to start the part of the
  platform that runs companies. Loud, at startup, once — rather than quiet,
  per company, per wake, forever.
* `UNVERIFIED` — anything else. The provider was unreachable, or answered in a
  shape this cannot read, or said the list was partial, or does not publish one
  at all. A warning, never a refusal.

That last verdict is the load-bearing one and it is deliberately generous. A
provider being down must not stop a platform that can still serve every read
surface an operator has — the dashboard, the activity feed, the approvals queue
are all database reads, and taking them away during a provider outage would
remove the operator's only view of the outage. And a rejection is the one
verdict here that can stop work that would otherwise have succeeded, so it is
issued only from evidence that is complete, non-empty, and current. Each of the
three guards in `verify_configured_model` closes one way a working deployment
could otherwise be refused by a check meant to protect it.

Nothing here reasons and nothing here spends: a catalog read is a GET, it is
free with every provider these transports cover, and no completion is issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.kernel.errors import JarvisError
from jarvis.kernel.logging import get_logger
from jarvis.llm.base import ModelCatalog

logger = get_logger(__name__)

UNREACHABLE_SUMMARY = "Jarvis couldn't check its thinking service just now, so it started anyway."
UNLISTED_SUMMARY = (
    "Jarvis can't start its companies: the thinking service it is set up to use "
    "doesn't offer the option named in your configuration."
)
UNLISTED_REMEDY = "Set JARVIS_LLM__MODEL in .env to one the provider offers."
"""Spec §12.5 in a place an operator may never look, and written that way on
purpose.

These reach a log line and, on the rejection path, a `ConfigurationError` whose
`operator_message` the shell may render. The register is the same one preflight
uses ("Companies can't think yet — no model key is configured"): what it means
and what to do, never which exception fired. `JARVIS_LLM__MODEL` is a
configuration key rather than platform vocabulary — it is the literal thing the
person fixing this has to edit, and preflight's own remedies already name it."""


class ModelVerdict(StrEnum):
    """What the startup check was able to establish."""

    CONFIRMED = "confirmed"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ModelCheck:
    """One verdict with the sentences that go with it."""

    verdict: ModelVerdict
    summary: str
    """Operator language (§12.5). Empty when there is nothing to say."""

    detail: str = ""
    """Engineer-facing. Drill-down and logs only."""

    remedy: str = ""
    """What to do about it, when there is something to do."""


async def verify_configured_model(provider: object, model: str) -> ModelCheck:
    """Check `model` against what `provider` says it offers.

    Args:
        provider: The built LLM provider. Typed `object` rather than
            `LLMProvider` because what this needs is the *other* protocol —
            `ModelCatalog` — and a provider may implement one without the
            other; the `isinstance` below is the actual requirement.
        model: The configured model id (`Settings.llm.model`).

    Returns:
        The verdict. Never raises: a startup check that can fail in a way the
        caller has to handle separately has just moved the problem.
    """
    if not isinstance(provider, ModelCatalog):
        return ModelCheck(
            ModelVerdict.UNVERIFIED,
            UNREACHABLE_SUMMARY,
            detail="this provider publishes no model catalog",
        )

    try:
        listing = await provider.list_models()
    except JarvisError as exc:
        # `ProviderError` is what every transport normalises its failures to, so
        # catching the family rather than the member keeps this from having to
        # know which vendor is configured. Unreachable, refused, or unparseable
        # all mean the same thing here: no evidence either way.
        return ModelCheck(
            ModelVerdict.UNVERIFIED,
            UNREACHABLE_SUMMARY,
            detail=exc.technical_detail,
        )

    if not listing.complete:
        # The provider said there was more than it sent. A model absent from a
        # partial list is not absent.
        return ModelCheck(
            ModelVerdict.UNVERIFIED,
            UNREACHABLE_SUMMARY,
            detail="the provider returned only part of its model list",
        )
    if not listing.ids:
        # A complete list of nothing is not a provider that offers nothing; it
        # is a response this code did not understand. Treating it as grounds for
        # refusal would turn one unrecognised catalog shape into a platform that
        # will not start.
        return ModelCheck(
            ModelVerdict.UNVERIFIED,
            UNREACHABLE_SUMMARY,
            detail="the provider's model list came back empty",
        )
    if model not in listing.ids:
        return ModelCheck(
            ModelVerdict.REJECTED,
            UNLISTED_SUMMARY,
            detail=(
                f"configured model {model!r} is not among the {len(listing.ids)} "
                "this provider currently lists"
            ),
            remedy=UNLISTED_REMEDY,
        )
    return ModelCheck(ModelVerdict.CONFIRMED, "")


__all__ = [
    "UNLISTED_REMEDY",
    "UNLISTED_SUMMARY",
    "UNREACHABLE_SUMMARY",
    "ModelCheck",
    "ModelVerdict",
    "verify_configured_model",
]
