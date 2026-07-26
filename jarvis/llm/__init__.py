"""Provider-agnostic LLM interface.

Business logic, workflows, capabilities, and managers never import a provider
module. They depend on the `LLMProvider` protocol and receive an instance by
injection, so changing vendor is a configuration change (A-005).
"""
