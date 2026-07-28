"""Provenance — the static head only (design EXECUTIVE-GOVERNANCE.md Part 3, D-048).

The owner's ninth revision-2 direction: every governed value carries
provenance, ``Origin -> Modified By -> Approved By -> Executed By``. **This
module carries only the static half.** Origin, Modified By and Approved By
are properties of the value itself and are stored beside it (Part 3.2);
Executed By is a property of *each use* and belongs to a Decision Lineage
node (Part 4), never to this record — storing it here would silently
overwrite the last executor with the current one, a schema that cannot hold
its own definition (**M9-F139**). The dynamic tail is a later wave's
territory; this module never grows an ``executed_by`` field, and any change
that tries to is re-introducing the bug Part 3.2 named.

:class:`ProvenanceHead` is designed to attach, additively, to the contract
models that already carry governed values — see the ``provenance`` field on
``AutonomyPolicy``, ``BudgetPolicy``, ``WakeConditions``,
``CapabilityPermission`` and ``KpiTarget`` in ``jarvis/domain/contract.py``.
Every field defaults, so a contract stored before this module existed
deserializes unchanged — the same additive-with-a-default shape
``KpiTarget.direction`` already proved against a pre-field contract snapshot
(M7-F30, ``tests/test_contract.py``). No migration follows from adding it:
the whole contract is one JSON column (``BusinessInstanceRow.contract``).

An empty provenance head — ``origin=PLATFORM_DEFAULT``, ``modified_by=None``,
``approved_by=None`` — is the correct starting state for every value on the
platform today: no approval has ever authorised a configuration change
(Part 3.5). Honestly empty, not absent.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Origin(StrEnum):
    """Where a governed value's current setting came from (Part 3.1).

    Five recordable values. Only three are *permitted* for a policy — an
    ``ENFORCING``-class parameter (Part 2.1; see
    ``jarvis.registry.parameter_register.PERMITTED_POLICY_ORIGINS``) — the
    other two are recordable precisely so their presence on a policy is
    visible as the violation it is, never treated as a legitimate origin.
    """

    OWNER = "owner"
    """Set directly by the owner: an approval, or a direct edit."""

    SPECIFICATION = "specification"
    """Fixed by the architecture spec itself (e.g. D-022's price bound)."""

    APPROVED_CONFIG = "approved_config"
    """Read from deployment configuration the owner controls (``Settings``,
    ``.env``) — the owner's second permitted origin."""

    TYPE_DEFINITION = "type_definition"
    """Supplied by a business type's own declaration — a *request*, per the
    owner's plugin trichotomy (Part 8.3). Recordable, never permitted for a
    policy: a type may ask, never establish."""

    PLATFORM_DEFAULT = "platform_default"
    """A Python code default, chosen by whoever wrote the field, with no
    owner, spec, or config decision behind it. Recordable so its presence on
    a policy is visible as the violation it is (**M9-F130**) — never a
    permitted origin."""


PERMITTED_POLICY_ORIGINS: frozenset[Origin] = frozenset(
    {Origin.OWNER, Origin.SPECIFICATION, Origin.APPROVED_CONFIG}
)
"""The owner's origin clause (Part 2.1, verbatim): a policy's Origin must be
one of these three, or it is not a legitimate policy no matter how long the
platform has been enforcing it (**M9-F130**)."""


class ProvenanceHead(BaseModel):
    """The static half of provenance: Origin, Modified By, Approved By.

    Deliberately excludes ``Executed By`` — see the module docstring and
    **M9-F139**. Frozen like the contract models it attaches to (``_Contract``
    in ``jarvis/domain/contract.py``): a provenance head is replaced
    wholesale when the value it describes changes, never mutated field by
    field, so ``modified_by`` always names the actor behind the value it is
    currently attached to rather than accumulating a history this shape was
    never designed to hold — that history is Decision Lineage's job.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: Origin = Origin.PLATFORM_DEFAULT
    """Defaults honestly empty (Part 3.5): every value on the platform today
    reached its current setting with no owner-authorised change on record."""

    modified_by: str | None = None
    """Actor identifier of the last change, or None if never modified."""

    approved_by: str | None = None
    """Approval id, ``"OWNER_DIRECT"``, or None. Empty for every value on the
    platform today (Part 3.5) — no approval has ever authorised a
    configuration change."""
