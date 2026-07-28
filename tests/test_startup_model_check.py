"""The startup model check, and the three ways it must not fire (M9-F118).

**The defect.** Nothing ever compared `settings.llm.model` against reality until
the first paid reasoning call of the first company to wake. So a model id that
was simply wrong looked exactly like a provider outage — three companies'
rounds failing seconds apart on `HTTP 404`, retries spent, budget reserved and
released, and no way to tell "you configured a model that does not exist" from
"the provider is having a bad minute" without a human reading logs.

**The fix, and why most of this file is about the fix not firing.** A refusal
is the one verdict that can stop work which would otherwise have succeeded, so
`verify_configured_model` issues it only from a list that is complete,
non-empty, and actually retrieved. Each of those is a way a healthy deployment
could otherwise be refused by the check meant to protect it — a paginated
catalog, an unrecognised response shape, a provider having the very outage this
was written for — and each gets a test here, because a startup guard that turns
a blip into a refusal to start is a worse defect than the one it replaces.

Every request is served by `httpx.MockTransport`: no network, no key, $0.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from jarvis.kernel.config import LLMProviderName, LLMSettings, Settings
from jarvis.kernel.errors import ConfigurationError, ProviderError
from jarvis.llm.base import ModelCatalog, ModelListing
from jarvis.llm.providers.anthropic import AnthropicProvider
from jarvis.llm.validation import ModelVerdict, verify_configured_model

CONFIGURED = "configured-model"


class _Catalog:
    """A provider that answers `list_models` and nothing else.

    Deliberately not an `LLMProvider`: the check must depend on the narrow
    protocol only, and a stub that implemented both would let a dependency on
    the wide one pass unnoticed.
    """

    def __init__(self, listing: ModelListing | Exception) -> None:
        self._listing = listing

    async def list_models(self) -> ModelListing:
        if isinstance(self._listing, Exception):
            raise self._listing
        return self._listing


class _NoCatalog:
    """A transport with no catalog at all — a future vendor, or a private
    endpoint that publishes nothing."""


def test_the_narrow_protocol_is_what_is_checked() -> None:
    """`ModelCatalog` is a second protocol, not a widening of `LLMProvider`.

    Business logic may never ask which models exist — the model is
    configuration (A-005), and a Manager that could enumerate models could
    choose one. Keeping the catalog on its own protocol is what makes that
    true structurally rather than by convention.
    """
    assert isinstance(_Catalog(ModelListing()), ModelCatalog)
    assert not isinstance(_NoCatalog(), ModelCatalog)


async def test_a_listed_model_is_confirmed() -> None:
    listing = ModelListing(ids=("other-model", CONFIGURED), complete=True)
    check = await verify_configured_model(_Catalog(listing), CONFIGURED)
    assert check.verdict is ModelVerdict.CONFIRMED


async def test_a_model_the_provider_does_not_list_is_refused() -> None:
    """The fix itself: the one case where startup stops.

    Complete list, real entries, configured model absent. Every future round
    would spend its retries rediscovering this, so it is said once, loudly, at
    startup instead.
    """
    listing = ModelListing(ids=("one-model", "another-model"), complete=True)
    check = await verify_configured_model(_Catalog(listing), CONFIGURED)

    assert check.verdict is ModelVerdict.REJECTED
    assert check.remedy, "a refusal an operator cannot act on is just a stop"
    assert CONFIGURED in check.detail, "the engineer-facing half names what was configured"
    assert CONFIGURED not in check.summary, "the operator-facing half is a sentence, not a value"


async def test_an_unreachable_provider_is_a_warning_not_a_refusal() -> None:
    """The posture the incident forces (packet M9-7).

    The API being down must not stop a platform that can still serve every read
    surface an operator has — and during a provider outage those surfaces are
    the only view of the outage there is. Refusing to start on a failed
    *diagnostic* would manufacture the outage it was checking for.
    """
    check = await verify_configured_model(
        _Catalog(ProviderError("anthropic returned HTTP 404")), CONFIGURED
    )
    assert check.verdict is ModelVerdict.UNVERIFIED


async def test_a_partial_list_never_refuses() -> None:
    """A model absent from one page is not absent.

    Every catalog endpoint these transports read is paginated. Without this
    guard the first provider to grow past a page turns a configured, working
    model into a refusal nobody can explain — the check's own worst failure
    mode, and the reason `ModelListing` carries `complete` at all.
    """
    listing = ModelListing(ids=("one-model",), complete=False)
    check = await verify_configured_model(_Catalog(listing), CONFIGURED)
    assert check.verdict is ModelVerdict.UNVERIFIED


async def test_an_empty_list_never_refuses() -> None:
    """A complete list of nothing is a response this code did not understand.

    No provider offers zero models. Reading that as "your model is not offered"
    would turn one unrecognised catalog shape — a vendor renaming a field —
    into a platform that will not start.
    """
    check = await verify_configured_model(_Catalog(ModelListing(complete=True)), CONFIGURED)
    assert check.verdict is ModelVerdict.UNVERIFIED


async def test_a_provider_with_no_catalog_starts_normally() -> None:
    """A transport that publishes no list is not a defect; it is the old
    behaviour, which was to find out at the first reasoning call."""
    check = await verify_configured_model(_NoCatalog(), CONFIGURED)
    assert check.verdict is ModelVerdict.UNVERIFIED


# ── the transports' own catalog reads ──────────────────────────────────────


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://x")


def _settings(provider: LLMProviderName) -> LLMSettings:
    return LLMSettings(provider=provider, model=CONFIGURED, api_key="test-key")


async def test_anthropic_reports_a_truncated_catalog_as_incomplete() -> None:
    """`has_more` is carried through rather than paged after.

    The caller treats an incomplete list as "cannot tell", so a second request
    would buy a stronger claim than the check is allowed to make anyway — and
    a transport that silently dropped the flag would hand it a confident wrong
    answer instead.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "one-model"}, {"id": CONFIGURED}], "has_more": True},
        )

    provider = AnthropicProvider(_settings(LLMProviderName.ANTHROPIC), _client(handler))
    listing = await provider.list_models()

    assert listing.ids == ("one-model", CONFIGURED)
    assert listing.complete is False
    assert requests[0].url.path == "/v1/models"
    assert requests[0].method == "GET", "a catalog read is free; a completion is not"


async def test_a_catalog_failure_normalises_like_any_other_provider_failure() -> None:
    """`get_json` is the read half of `post_json`, including its refusal to log
    bodies (spec §10) — so a caller cannot branch on vendor error shapes here
    any more than it can on the completion path."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    provider = AnthropicProvider(_settings(LLMProviderName.ANTHROPIC), _client(handler))
    with pytest.raises(ProviderError):
        await provider.list_models()


# ── what a verdict does to startup ─────────────────────────────────────────


class _StubKernel:
    """Only what `run_worker` reads before it decides (M9-F118)."""

    def __init__(self, listing: ModelListing | Exception) -> None:
        self.settings = Settings(  # type: ignore[call-arg]
            llm=LLMSettings(model=CONFIGURED),
            _env_file=None,
        )
        """`_env_file=None`: the repository holds a real `.env`, and a test that
        read it would reach a live provider."""

        self.llm = _Catalog(listing)


class _ReachedTemporalError(Exception):
    """Raised by the stubbed client to prove startup got past the check."""


async def test_a_refused_model_stops_the_worker_before_it_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loud failure, and where it lands.

    Under the launcher the worker is a supervised part, so this shows as
    "Company runner — restarting" in the health banner with a reason in the log
    — while the dashboard, activity feed and approvals queue keep serving. The
    assertion that it never reached Temporal is the point: the refusal is a
    startup decision, not something a company discovers mid-round.
    """
    from jarvis.runtime import worker as worker_module

    async def _connect(*_: object, **__: object) -> None:
        raise _ReachedTemporalError

    monkeypatch.setattr(worker_module.Client, "connect", _connect)
    kernel = _StubKernel(ModelListing(ids=("one-model",), complete=True))

    with pytest.raises(ConfigurationError) as raised:
        await worker_module.run_worker(kernel)  # type: ignore[arg-type]
    assert raised.value.operator_message, "§12.5: the stop says what it means for the operator"


async def test_an_unverifiable_model_lets_the_worker_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control on the refusal, driven through `run_worker` itself.

    A check that could not reach the provider must leave startup exactly as it
    was. Proved by the stubbed connect being reached — anything short of that
    would mean the warning path had quietly become a second refusal.
    """
    from jarvis.runtime import worker as worker_module

    async def _connect(*_: object, **__: object) -> None:
        raise _ReachedTemporalError

    monkeypatch.setattr(worker_module.Client, "connect", _connect)
    kernel = _StubKernel(ProviderError("anthropic transport failure: ConnectError"))

    with pytest.raises(_ReachedTemporalError):
        await worker_module.run_worker(kernel)  # type: ignore[arg-type]
