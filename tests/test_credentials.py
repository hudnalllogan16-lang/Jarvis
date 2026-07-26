"""Credential manager tests (spec §10)."""

from __future__ import annotations

import pytest

from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import ScopeViolationError
from jarvis.security.credentials import CredentialManager


def _manager() -> CredentialManager:
    return CredentialManager({"serp_key": "real-secret", "brokerage_key": "other-secret"})


def test_granted_and_permitted_handle_resolves(contract: BusinessContract) -> None:
    secret = _manager().resolve(
        contract=contract, handle="serp_key", granted_handles=frozenset({"serp_key"})
    )
    assert secret.get_secret_value() == "real-secret"


def test_secret_is_wrapped_so_it_cannot_leak_by_interpolation(
    contract: BusinessContract,
) -> None:
    """Spec §10: secrets must not appear in code, logs, or prompts."""
    secret = _manager().resolve(
        contract=contract, handle="serp_key", granted_handles=frozenset({"serp_key"})
    )
    assert "real-secret" not in str(secret)
    assert "real-secret" not in repr(secret)


def test_handle_not_granted_to_this_invocation_is_refused(
    contract: BusinessContract,
) -> None:
    """Spec §2.2: credential scope is per invocation, not per business."""
    with pytest.raises(ScopeViolationError):
        _manager().resolve(contract=contract, handle="serp_key", granted_handles=frozenset())


def test_handle_not_permitted_to_this_business_is_refused(
    contract: BusinessContract,
) -> None:
    """Defence in depth: catches a path that reached here without the pool."""
    with pytest.raises(ScopeViolationError):
        _manager().resolve(
            contract=contract,
            handle="brokerage_key",
            granted_handles=frozenset({"brokerage_key"}),
        )


def test_unknown_handle_is_refused(contract: BusinessContract) -> None:
    manager = CredentialManager({})
    with pytest.raises(ScopeViolationError):
        manager.resolve(
            contract=contract, handle="serp_key", granted_handles=frozenset({"serp_key"})
        )


def test_refusals_do_not_echo_secret_values(contract: BusinessContract) -> None:
    """A probing caller must learn nothing from the failure message."""
    with pytest.raises(ScopeViolationError) as exc:
        _manager().resolve(
            contract=contract,
            handle="brokerage_key",
            granted_handles=frozenset({"brokerage_key"}),
        )
    assert "other-secret" not in exc.value.technical_detail


def test_available_handles_exposes_names_only() -> None:
    assert _manager().available_handles() == {"serp_key", "brokerage_key"}
