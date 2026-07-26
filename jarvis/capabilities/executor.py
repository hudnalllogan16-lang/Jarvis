"""Capability execution shell (spec §6, §2.2).

A capability is a stateless execution shell: it receives a scoped request, loads
only what that request grants, completes the task, writes results, and
terminates (spec §6). Statelessness is enforced structurally rather than by
convention — the executor holds no per-invocation attributes, so there is no
field in which residual memory, credentials, or context could survive into the
next call (spec §2.2).

The base prompt is generic by construction. Domain content arrives by reference
in the request, never baked into the capability (spec §2.2).
"""

from __future__ import annotations

from typing import Protocol, TypeGuard

from jarvis.capabilities.request import PRIOR_RESULTS_KEY, MemoryScope, ScopedRequest
from jarvis.domain.contract import BusinessContract, CapabilityType
from jarvis.kernel.errors import CapabilityExecutionError, ProviderError
from jarvis.llm.base import CompletionRequest, LLMProvider, Message, Role, StopReason, Usage

BASE_PROMPTS: dict[CapabilityType, str] = {
    CapabilityType.RESEARCH: "You are a research capability. Gather and summarise evidence.",
    CapabilityType.FINANCE: "You are a finance capability. Analyse figures precisely.",
    CapabilityType.DEVELOPMENT: "You are a development capability. Produce working code.",
    CapabilityType.CONTENT: "You are a content capability. Draft clear written material.",
    CapabilityType.DESIGN: "You are a design capability. Produce design specifications.",
    CapabilityType.COMPLIANCE: "You are a compliance capability. Assess against stated rules.",
    CapabilityType.OPERATIONS: "You are an operations capability. Execute operational tasks.",
}
"""Generic base prompts. None names a business, a domain, or a vendor."""


class PromptTemplates(Protocol):
    """Resolves a business's prompt reference to template text."""

    def resolve(self, prompt_ref: str) -> str:
        """Return the template for ``prompt_ref``.

        Raises:
            KeyError: If the reference is unknown.
        """
        ...


class InMemoryTemplates:
    """Dictionary-backed template source, used until plugin loading exists."""

    def __init__(self, templates: dict[str, str]) -> None:
        """Args:
        templates: Reference-to-template mapping.
        """
        self._templates = dict(templates)

    def resolve(self, prompt_ref: str) -> str:
        """Return the template for ``prompt_ref``.

        Raises:
            KeyError: If the reference is unknown.
        """
        return self._templates[prompt_ref]


class CapabilityExecutor:
    """Executes one scoped request and returns its output.

    Holds only collaborators that are identical across every invocation. It
    deliberately stores nothing derived from a request, which is what makes
    spec §2.2's "no residual context between calls, including consecutive calls
    for the same business" true by construction rather than by discipline.
    """

    def __init__(self, provider: LLMProvider, templates: PromptTemplates) -> None:
        """Args:
        provider: Configured LLM provider, injected by the Kernel.
        templates: Prompt template source.
        """
        self._provider = provider
        self._templates = templates

    async def execute(
        self,
        *,
        request: ScopedRequest,
        contract: BusinessContract,
        memory_context: str = "",
    ) -> tuple[str, Usage]:
        """Execute one invocation.

        Args:
            request: The scoped request.
            contract: The invoking business's contract, for display naming only.
            memory_context: Memory the request was granted (spec §7). Empty
                unless `memory_scope` grants read access — a capability has no
                ambient access to a business's memory.

        Returns:
            A tuple of output text and token usage.

        Raises:
            CapabilityExecutionError: On an unknown prompt reference (permanent,
                so retrying only burns budget) or a provider failure (transient,
                so it is retried per spec §9).
        """
        try:
            template = self._templates.resolve(request.prompt_ref)
        except KeyError as exc:
            raise CapabilityExecutionError(
                f"unknown prompt reference {request.prompt_ref!r}",
                permanent=True,
                operator_message=f"{contract.display_name} is missing a task definition.",
            ) from exc

        if request.memory_scope is MemoryScope.NONE and memory_context:
            raise CapabilityExecutionError(
                "memory context supplied to an invocation granted no memory scope (spec §7)",
                permanent=True,
            )

        sections = [template.format(**request.prompt_inputs)]
        granted = _granted_prior_results(request)
        if granted:
            sections.append(granted)
        if memory_context:
            sections.append(f"Relevant prior context:\n{memory_context}")

        completion = CompletionRequest(
            messages=(Message(role=Role.USER, content="\n\n".join(sections)),),
            system=BASE_PROMPTS[request.capability],
        )

        try:
            response = await self._provider.complete(completion)
        except ProviderError as exc:
            raise CapabilityExecutionError(
                f"provider failure during {request.capability.value}: {exc.technical_detail}",
                operator_message=f"{contract.display_name} couldn't finish a task — retrying.",
            ) from exc

        if response.stop_reason is StopReason.CONTENT_FILTER:
            raise CapabilityExecutionError(
                "provider refused to complete the request",
                permanent=True,
                operator_message=f"{contract.display_name} couldn't complete a task.",
            )

        return response.text, response.usage


def _granted_prior_results(request: ScopedRequest) -> str:
    """Render the earlier results this invocation was granted (D-023 point 3).

    Its own labelled section, never interpolated into the business's template.
    A capability that received a prior draft spliced into its instructions could
    not tell the two apart, and §2.2's "no residual context between calls" means
    exactly that whatever a capability sees, it sees because the request granted
    it — visibly.

    Degrades rather than raises on a malformed value: the key is written by the
    Manager, but this is the boundary where an invocation stops trusting its
    caller's shape, and a formatting fault must not fail work already paid for.

    Returns:
        The section text, or an empty string when nothing was granted.
    """
    granted: object = request.prompt_inputs.get(PRIOR_RESULTS_KEY)
    if not _is_object_list(granted):
        return ""

    lines: list[str] = []
    for item in granted:
        if not _is_object_dict(item):
            continue
        ref = str(item.get("ref", ""))
        output = str(item.get("output", ""))
        if not output:
            continue
        lines.append(f"[{ref}]\n{output}" if ref else output)

    if not lines:
        return ""
    return "Results of earlier steps in this round of work:\n" + "\n\n".join(lines)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Type-guard: is ``value`` a list? Every element is trivially an ``object``."""
    return isinstance(value, list)


def _is_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Type-guard: is ``value`` a string-keyed dict?

    Safe because the only writer of this structure serialises it through the
    workflow/activity boundary, where it is JSON — and JSON objects have string
    keys. The runtime check is a plain ``isinstance``; the guard exists because
    that alone proves only ``dict[Unknown, Unknown]``.
    """
    return isinstance(value, dict)
