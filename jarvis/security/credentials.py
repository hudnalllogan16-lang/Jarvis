"""Credential manager (spec §10).

Spec §10 says secrets MUST NOT appear in code, logs, or prompts, while spec §2.2
gives every invocation a credential scope. v1.4 never says where the secret is
materialised, which is the gap that lets one engineer pass opaque handles into
model context and another inject live keys into tool configuration the model can
read.

This module fixes the boundary: the scoped request carries *handles*, and the
secret behind a handle is resolved here, at the tool-execution boundary, and
never travels through a prompt. `resolve` returns a `SecretStr` so an accidental
interpolation prints a placeholder rather than a key.

Resolution is also authorization-checked against the business's contract, which
is defence in depth — the pool already validated scope (D-002), and this catches
the case where a code path reaches a credential without going through the pool.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import SecretStr

from jarvis.domain.contract import BusinessContract
from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)


class CredentialManager:
    """Resolves credential handles to secrets at the tool-execution boundary."""

    def __init__(self, secrets: Mapping[str, str]) -> None:
        """Args:
        secrets: Handle-to-secret mapping supplied by the secrets manager.
            Injected rather than read from the environment here, so the
            production source can be swapped without touching this class.
        """
        self._secrets = dict(secrets)

    def resolve(
        self,
        *,
        contract: BusinessContract,
        handle: str,
        granted_handles: frozenset[str],
    ) -> SecretStr:
        """Resolve one credential handle for one business.

        Args:
            contract: The requesting business's contract.
            handle: The credential handle to resolve.
            granted_handles: Handles the current invocation was granted.

        Returns:
            The secret, wrapped so it cannot be logged or interpolated by
            accident.

        Raises:
            ScopeViolationError: If the handle was not granted to this
                invocation, is not permitted to this business by any capability
                permission, or is unknown. All three are refused identically and
                without echoing the handle's value, so a probing caller learns
                nothing from the difference.
        """
        if handle not in granted_handles:
            raise ScopeViolationError(
                f"credential handle {handle!r} was not granted to this invocation (spec §2.2)"
            )

        permitted = {
            ref
            for permission in contract.capability_permissions
            for ref in permission.credential_refs
        }
        if handle not in permitted:
            raise ScopeViolationError(
                f"business {contract.business_id} has no permission for credential "
                f"handle {handle!r} (spec §10)"
            )

        secret = self._secrets.get(handle)
        if secret is None:
            raise ScopeViolationError(
                f"credential handle {handle!r} is not present in the secrets manager"
            )
        return SecretStr(secret)

    def available_handles(self) -> frozenset[str]:
        """Return known handles. Handles only — never values."""
        return frozenset(self._secrets)
