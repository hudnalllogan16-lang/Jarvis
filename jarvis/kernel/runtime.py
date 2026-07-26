"""Runtime-derived business identity (spec §10, decision D-002).

D-002 requires that a capability invocation's business identity be *derived*
from the running workflow rather than declared by the request. Milestone 1's
first cut expressed that as a documented convention — `authorize_invocation`
accepted a plain `BusinessId` and trusted the caller to pass the right one. A
convention is not an enforcement: any caller could pass any string, which is
precisely the "bug or malformed request" case spec §10 says must not be able to
cross a business boundary.

This module closes that by making the identity a type that cannot be constructed
from a bare string in ordinary code. The only production constructor reads
Temporal's activity context, whose `workflow_id` is supplied by the Temporal
server from the *calling workflow*, not by code running inside the activity.
Activity code cannot forge it.

Workflow ids follow the convention ``bm-{business_id}`` for Business Manager
workflows. That convention is load-bearing: it is what ties a running workflow
back to a registered business, so it is validated here rather than assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from jarvis.kernel.errors import ScopeViolationError
from jarvis.kernel.ids import BusinessId

WORKFLOW_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^bm-(biz_[0-9a-f]{32})$")
"""Business Manager workflow id format. Anything else is not a business workflow."""


def business_workflow_id(business_id: BusinessId) -> str:
    """Return the deterministic workflow id for a business's Manager.

    Deterministic by construction so a Manager can be addressed without a lookup
    and so exactly one Manager can exist per business (spec §2.1).
    """
    return f"bm-{business_id}"


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """A business identity derived from the workflow runtime, not from a request.

    Deliberately not constructible from a plain string in calling code: the
    private ``_source`` field records how the identity was obtained, and every
    constructor is a classmethod that names its provenance. Passing a raw
    `BusinessId` where a `RuntimeIdentity` is expected is a type error, which is
    what turns D-002 from documentation into something Pyright enforces.

    Attributes:
        business_id: The derived business identifier.
        workflow_id: The workflow the identity came from.
        _source: Provenance, recorded in audit entries so that a trusted-source
            identity in a production audit trail is immediately visible as an
            anomaly.
    """

    business_id: BusinessId
    workflow_id: str
    _source: str

    @property
    def audit_source(self) -> str:
        """Provenance label for audit records.

        The one legitimate external reader of ``_source``: security denials
        record it so a non-"activity" provenance in a production audit trail
        is immediately visible as an anomaly (see the class docstring).
        Ordinary code has no business reading its own provenance back, so
        this is not exposed more broadly than the audit path that needs it.
        """
        return self._source

    @classmethod
    def from_activity(cls) -> RuntimeIdentity:
        """Derive identity from the current Temporal activity context.

        `activity.info().workflow_id` is populated by the Temporal server from
        the workflow that scheduled this activity. Activity code cannot set or
        alter it, which is what makes this derivation rather than declaration.

        Returns:
            The identity of the business whose Manager scheduled this activity.

        Raises:
            ScopeViolationError: If called outside an activity, if the activity
                was not started by a workflow, or if the workflow id does not
                identify a business workflow. All three are refused rather than
                defaulted — an unidentifiable caller is exactly the case §10
                exists to stop.
        """
        try:
            from temporalio import activity
        except ImportError as exc:  # pragma: no cover - dependency always present
            raise ScopeViolationError(
                "temporal runtime unavailable; cannot derive business identity"
            ) from exc

        if not activity.in_activity():
            raise ScopeViolationError(
                "business identity can only be derived inside an activity (D-002)"
            )
        # temporalio types `Info.workflow_id` as `str | None` — None when the
        # activity was not started by a workflow, which `in_activity()` does not
        # rule out. Such an activity has no calling workflow, so there is no
        # identity to derive: refuse it (M6-F4). Falling through would reach
        # `from_workflow_id` and raise a bare TypeError out of the regex, which
        # is a crash rather than a security refusal — it carries no audit-legible
        # reason and is the kind of failure a caller might be tempted to catch
        # broadly and default around.
        workflow_id = activity.info().workflow_id
        if workflow_id is None:
            raise ScopeViolationError(
                "activity was not started by a workflow, so it has no derivable "
                "business identity (D-002)"
            )
        return cls.from_workflow_id(workflow_id, source="activity")

    @classmethod
    def from_workflow_id(cls, workflow_id: str, *, source: str = "workflow_id") -> RuntimeIdentity:
        """Derive identity by parsing a server-supplied workflow id.

        Args:
            workflow_id: Workflow id as reported by the Temporal runtime.
            source: Provenance label for audit records.

        Returns:
            The derived identity.

        Raises:
            ScopeViolationError: If the workflow id is not a Business Manager
                workflow id.
        """
        match = WORKFLOW_ID_PATTERN.match(workflow_id)
        if match is None:
            raise ScopeViolationError(
                f"workflow id {workflow_id!r} does not identify a business workflow (D-002)"
            )
        return cls(BusinessId(match.group(1)), workflow_id, source)

    @classmethod
    def for_testing(cls, business_id: BusinessId) -> RuntimeIdentity:
        """Construct an identity outside a workflow. **Tests and bootstrap only.**

        Marked as such in the audit trail via ``_source``. If this provenance
        ever appears in a production audit record, an unauthenticated caller
        reached the authorization boundary and that is an incident, not a
        curiosity.

        The identifier is validated against the same pattern production uses.
        Without that, tests could pass with ids no real business would have, and
        the derivation path would only ever be exercised against convenient
        input.

        Raises:
            ScopeViolationError: If ``business_id`` is not a well-formed
                business identifier.
        """
        workflow_id = business_workflow_id(business_id)
        if WORKFLOW_ID_PATTERN.match(workflow_id) is None:
            raise ScopeViolationError(
                f"{business_id!r} is not a well-formed business identifier; "
                "test identities must match the production format"
            )
        return cls(business_id, workflow_id, "testing")
