# Jarvis Engineering Specification

**Document ID:** GOV-001
**Version:** 1.0
**Status:** Active
**Governed By:** Jarvis Constitution v1.0, Project Bible v1.0
**Last Updated:** 2026-07-24

---

## 1. Engineering Philosophy

### 1.1 Core Values

Jarvis is built on three non-negotiable values, ordered by priority:

1. **Correctness** — Wrong answers are worse than slow answers. A system that confidently produces incorrect results is a liability, not an asset.
2. **Safety** — The system protects user assets, data, and autonomy. Safety is not a feature; it is a prerequisite for every other feature.
3. **Maintainability** — Code must be understandable six months from now by someone who did not write it. Every decision should reduce long-term complexity.

### 1.2 Tradeoff Framework

When principles conflict, apply the following priority unless a specific requirement documented in an Architecture Decision Record (ADR) justifies otherwise:

| Priority | Principle | When to Override |
|----------|-----------|------------------|
| 1 | Correctness | Never |
| 2 | Safety | Never for financial/data-affecting operations |
| 3 | Maintainability | Performance requirements with measured benchmarks |
| 4 | Simplicity | When a simpler solution cannot satisfy current requirements |
| 5 | Extensibility | When speculative abstraction adds complexity without value |
| 6 | Performance | Only after profiling identifies a bottleneck |
| 7 | Convenience | Only when it does not compromise 1–6 |

### 1.3 Incremental Evolution

Every commit must leave the repository in a working state. No commit should intentionally break previous functionality. Backward-incompatible changes require:
- A migration path
- Explicit approval from the Chief Architect
- Documentation in an ADR

---

## 2. Repository Architecture and Boundaries

### 2.1 Layered Architecture

Jarvis is structured as a layered system with explicit contracts between layers. No layer may bypass the contract of an adjacent layer.

```
+-------------------------------------+
|         Applications                |  /apps
|  (Trading, Finance, Projects...)    |
+-------------------------------------+
|         Services                    |  /services
|  (LLM, Memory, Database, Logging)   |
+-------------------------------------+
|         Kernel                      |  /kernel
|  (Config, Registry, Events,         |
|   Interfaces, Security)             |
+-------------------------------------+
|         Infrastructure              |  /docker, external deps
|  (Compute, Storage, Networking)     |
+-------------------------------------+
```

### 2.2 Layer Rules

**Kernel (/kernel)**
- The minimal irreducible runtime. The only layer that cannot be replaced without rebuilding Jarvis.
- Contains: configuration bootstrap, service registry, event bus, interfaces, security primitives.
- Must not contain business logic, trading algorithms, or application-specific code.
- All kernel modules are packages (directories with __init__.py), never single files.

**Services (/services)**
- Reusable, domain-independent capabilities exposed through stable interfaces.
- Services may depend on the kernel (for configuration, interfaces, events).
- Services may NOT depend on applications.
- Services may depend on other services only through published interfaces, not direct imports.
- Each service is a package with its own tests, documentation, and lifecycle.

**Applications (/apps)**
- User-facing business logic built on top of services.
- Applications may depend on services and the kernel.
- Applications may NOT depend on other applications.
- Applications may NOT directly access infrastructure (databases, external APIs) — they must route through services.
- Each application is a package. Sub-packages (e.g., agents/, logic/, api/) are permitted.

**Shared Code**
- Avoid introducing a repository-level shared package unless a genuine cross-cutting concern exists.
- Shared packages should not become dumping grounds for unrelated utilities.
- Place code in the narrowest layer that owns it whenever possible.
- Truly universal utilities belong in /kernel/utils/ or /kernel/types.py.
- Service-specific utilities belong in /services/<name>/utils/.
- Application-specific utilities belong in /apps/<name>/utils/.

### 2.3 Dependency Rules

```
apps -> services -> kernel
  \______________/
```

- **Allowed:** apps -> services, apps -> kernel, services -> kernel
- **Forbidden:** apps -> apps, services -> apps, kernel -> services, kernel -> apps
- **Circular dependencies are prohibited at all layers.**

### 2.4 Interface Boundaries

Every major subsystem begins with a versioned interface. Implementations come later.

- Interface definitions live in /kernel/interfaces/ or /services/<name>/interface/v1/.
- All service interfaces are versioned using semantic versioning for APIs.
- Backward-incompatible changes require a new major version and a migration window.
- Applications interact with services through interfaces, not implementations.

---


## 2.5 Architectural Invariants

These are permanent project rules. They govern every future architectural and engineering decision within Jarvis. They may not be overridden by local convenience.

### AI Provider Independence

Jarvis must remain provider-agnostic by design.

- No component outside `services/llm` may directly depend on an AI provider SDK.
- Applications, services, and the kernel must interact only with the LLM abstraction.
- Supported providers may include Kimi, OpenAI, Anthropic, Gemini, Ollama, local models, and future providers.
- Switching providers should require configuration changes rather than application code changes whenever practical.

### Incremental Development

Jarvis is developed milestone by milestone.

- Completed milestones are considered stable.
- Do not redesign or refactor completed milestones unless explicitly instructed.
- Extend the existing architecture rather than replacing it.

### Dependency Direction

Maintain these dependency rules without exception:

- **Kernel** depends on nothing outside itself.
- **Services** may depend on the kernel.
- **Applications** may depend on the kernel and services.
- **Applications** must never directly depend on other applications.
- Circular dependencies are prohibited at all layers.

### Interface-First Design

Prefer interfaces and protocols at architectural boundaries.

- Concrete implementations should be replaceable with minimal impact.
- Avoid tightly coupling consumers to specific implementations.
- Every major subsystem begins with a versioned interface before implementation.

### Extensibility

Design every subsystem with future expansion in mind.

- Do not assume Jarvis will only ever have one AI provider, one broker, one exchange, one database, one memory backend, or one notification provider.
- Favor abstractions that make additional implementations straightforward.
- The default implementation should be the simplest one that satisfies current requirements, but the interface must accommodate alternatives.

## 3. Python Coding Standards

### 3.1 Language Version

- **Target:** Python 3.14
- **Minimum:** Python 3.12 (for compatibility during transition)
- All code must run on the target version. Features exclusive to newer versions may be used only if they are backward-compatible with the minimum version.

### 3.2 General Principles

- **Functions do one thing.** If a function requires a comment to explain what it does, it should be split.
- **Classes have one responsibility.** Follow the Single Responsibility Principle.
- **Prefer explicit code over clever code.** Readability is not negotiable.
- **Avoid unnecessary abstractions.** Do not build for hypothetical future problems.
- **Avoid premature optimization.** Optimize only after measurement.
- **Code should be understandable six months later.** This is the minimum bar for acceptance.

### 3.3 Naming Conventions

| Construct | Convention | Example |
|-----------|------------|---------|
| Modules | snake_case | jarvis_settings.py |
| Packages | snake_case | service_registry |
| Classes | PascalCase | JarvisSettings |
| Functions | snake_case | load_settings() |
| Constants | UPPER_SNAKE_CASE | LOG_LEVELS |
| Private members | _leading_underscore | _validate_log_level() |
| Type variables | T, T_co, T_contra | T = TypeVar("T") |
| Enums | PascalCase class, UPPER_SNAKE_CASE members | LogLevel.DEBUG |

### 3.4 Function and Class Guidelines

- **Function length:** Target less-than-or-equal 50 lines. Hard limit: 100 lines. Exceeding 50 requires justification in code review.
- **Class length:** Target less-than-or-equal 300 lines. Hard limit: 500 lines. Exceeding 300 suggests the class has too many responsibilities.
- **Parameters:** Target less-than-or-equal 5 positional parameters. Use dataclasses or config objects for complex parameter sets.
- **Return values:** Prefer named return types over tuples. Use dataclasses or TypedDict for multiple return values.

### 3.5 Import Style

- Use absolute imports. Relative imports are forbidden except within test files.
- Group imports in three blocks separated by blank lines:
  1. Standard library
  2. Third-party packages
  3. Local application imports
- Sort imports alphabetically within each group.
- No wildcard imports (from module import *).

### 3.6 Formatting

- **Line length:** 100 characters.
- **Formatter:** Ruff (replaces Black, isort, and many flake8 plugins).
- All code must pass `ruff check` and `ruff format --check` before merge.

---

## 4. Type Hint Requirements

### 4.1 Mandatory Typing

- **All public functions and methods must have type hints.**
- **All class attributes must have type annotations.**
- **Return types must be explicit.** No implicit None returns.
- Type coverage target: greater-than-or-equal 95% of public API surface.

### 4.2 Type Checker

- **Tool:** Pyright in strict mode.
- All code must pass `pyright` with zero errors and zero warnings before merge.
- `Any` is forbidden unless justified with a `# type: ignore[reason]` comment and documented in the function docstring.

### 4.3 Type Patterns

- Use `StrEnum` over `Literal` for closed sets of string values (enables `is` comparisons and IDE autocomplete).
- Use `TypedDict` for dictionary structures with known keys.
- Use `dataclasses` or Pydantic models for structured data.
- Use `Protocol` for structural subtyping (duck typing with type safety).
- Prefer `type[X]` over `Type[X]` (Python 3.12+ syntax).
- Prefer `dict[K, V]` over `Dict[K, V]`, `list[T]` over `List[T]`, etc.

### 4.4 Generics

- Use generics when a function or class operates on arbitrary types.
- Type variables must be bound when possible: `T = TypeVar("T", bound=BaseClass)`.
- Avoid unconstrained `TypeVar` unless truly necessary.

---

## 5. Error Handling Standards

### 5.1 Philosophy

- **Fail fast.** Invalid state should be detected as early as possible.
- **Never silently ignore errors.** Every error path must be explicit.
- **Never use bare `except:` clauses.** Always catch specific exceptions.

### 5.2 Custom Exceptions

- Every module or package should define a base exception inheriting from `Exception`.
- Specific errors inherit from the module base exception.
- Exception names must end in `Error` (not `Exception`).
- Exception messages must be actionable. They should explain what went wrong and, where possible, how to fix it.

Example:

```python
class RegistryError(Exception):
    """Base exception for all registry operations."""


class DuplicateRegistrationError(RegistryError):
    """Raised when attempting to register an interface that is already registered."""
```

### 5.3 Error Propagation

- Do not catch exceptions just to re-raise them. Let them propagate unless you are adding context.
- When adding context, use `raise NewError("context") from original` to preserve the chain.
- Functions that can fail must document failure modes in their docstrings under a `Raises:` section.

### 5.4 Validation

- Input validation belongs at the boundary of a module (public API).
- Internal functions may assume valid input (defensive programming at the perimeter, not everywhere).
- Use Pydantic for configuration and external input validation.
- Use `assert` only for invariants that should never be false (internal logic checks), never for user input validation.

---

## 6. Testing Standards

### 6.1 Test Philosophy

- **Tests are not optional.** They are part of the implementation, not an afterthought.
- **A feature is not complete without tests.** See Definition of Done in the Project Bible.
- **Tests must be hermetic.** They must not depend on external state, environment variables, or filesystem state unless explicitly mocked.

### 6.2 Test Structure

```
kernel/tests/           # Kernel integration tests
services/<name>/tests/  # Service unit tests
apps/<name>/tests/      # Application unit tests
tests/                  # Cross-cutting integration and E2E tests
```

- Unit tests live with their code (in-package `tests/` directories).
- Integration tests live at the repository root in `/tests/`.
- Test files are named `test_<module>.py`.
- Test classes are named `Test<Feature>`.
- Test methods are named `test_<description>`.

### 6.3 Test Coverage

| Layer | Minimum Coverage | Notes |
|-------|------------------|-------|
| Kernel | 90% | Critical infrastructure, high confidence required |
| Services | 80% | Business logic and public APIs |
| Applications | 70% | Business logic; UI/API integration tested separately |
| Integration | N/A | Critical user journeys only |

Coverage is measured by line coverage of business logic, not boilerplate.

### 6.4 Test Patterns

- Use `pytest` as the test runner.
- Use `pytest.raises()` for exception testing.
- Use `monkeypatch` for environment and object mocking.
- Use fixtures for shared test setup.
- Use parametrized tests for multiple similar cases.
- Avoid `unittest.mock` unless necessary; prefer dependency injection and test doubles.

### 6.5 Test Data

- Do not use production data in tests.
- Use factory functions or fixtures to generate test data.
- Test data should be minimal but realistic.

---

## 7. Documentation Standards

### 7.1 Docstring Requirements

- **All public modules, classes, methods, and functions must have docstrings.**
- **All docstrings use Google style.**
- Private members (leading underscore) should have docstrings if their behavior is non-obvious.

Google style structure:

```python
def function_name(param: str) -> int:
    """Short one-line summary.

    Longer description if needed. Explains what the function does,
    when to use it, and any important caveats.

    Args:
        param: Description of the parameter.

    Returns:
        Description of the return value.

    Raises:
        SpecificError: When and why this is raised.
    """
```

### 7.2 Module Docstrings

Every module must begin with a docstring explaining:
- What the module does
- Its position in the architecture
- Any important design decisions or constraints

### 7.3 Architecture Decision Records (ADRs)

Major architectural decisions must be documented under `docs/architecture/adr/`.

#### ADR Format

Each ADR is a standalone Markdown file named `NNN-short-title.md` and must include:

1. **Problem** — What decision needed to be made and why it mattered.
2. **Decision** — The chosen approach.
3. **Alternatives Considered** — Other options evaluated and why they were rejected.
4. **Rationale** — Why the chosen approach is the best fit for Jarvis.
5. **Consequences** — Trade-offs, risks, and future implications.

#### ADR Lifecycle

- **Proposed:** Drafted during architecture review.
- **Accepted:** Ratified by the Chief Architect and Founder.
- **Superseded:** Replaced by a newer ADR. The old ADR is updated with a link to its successor.
- **Rejected:** Documented for historical context even if not chosen.

#### Examples of Future ADRs

| ADR Topic | Description |
|-----------|-------------|
| Dependency Injection Architecture | How services and applications receive their dependencies. |
| Event Bus Design | Internal message routing, async vs. sync, delivery guarantees. |
| Provider Abstraction | How the LLM service abstracts multiple AI providers. |
| Memory Architecture | Tiered memory design (working, episodic, semantic, procedural). |
| Trading Engine Architecture | Execution flow, safety guardrails, autonomy levels. |

The purpose of ADRs is to preserve architectural reasoning as Jarvis evolves. When a future developer asks "why was it built this way?", the ADR is the answer.

Significant architectural decisions must also be recorded in `/docs/adr/`:
- File naming: `NNN-short-title.md`
- Template: Context, Decision, Consequences, Status
- ADRs are immutable after acceptance. New information requires a new ADR that supersedes the old one.

### 7.4 README and Onboarding

- `/README.md` provides project overview and quick start.
- `/docs/` contains detailed documentation organized by topic.
- Every service and application should have its own `README.md` explaining its purpose, interface, and usage.

---


## 8. Logging Standards

### 8.1 Philosophy

- **Logging is not printf debugging.** It is a production observability tool.
- Every significant action, state change, and error must be logged.
- Logs must be structured (JSON) to enable automated parsing and querying.

### 8.2 Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Detailed diagnostic information. Useful for development, disabled in production. |
| INFO | Normal operations. System startup, task completion, state transitions. |
| WARNING | Unexpected but handled situations. Degraded performance, retries, timeouts. |
| ERROR | Failures that affect a specific operation but not the whole system. |
| CRITICAL | System-wide failures. The application cannot continue safely. |

### 8.3 Structured Logging

All logs must be structured JSON with at minimum:
- `timestamp` — ISO 8601 format
- `level` — Log level
- `logger` — Logger name (module path)
- `message` — Human-readable message
- `correlation_id` — Request/task trace ID (when available)
- `context` — Additional structured data (user ID, operation type, etc.)

### 8.4 Sensitive Data

- **Never log secrets, API keys, passwords, or tokens.**
- **Never log PII (personally identifiable information) at INFO or below.**
- PII may be logged at DEBUG only in development environments, and must be explicitly marked.
- Use `SecretStr` and similar types to prevent accidental logging.

### 8.5 Logger Naming

- Loggers are named hierarchically using module paths: `kernel.config.loader`, `services.llm.client`.
- Logger configuration is inherited hierarchically.
- Each major subsystem has its own logger.

---

## 9. Security Considerations

### 9.1 Secrets Management

- **Secrets never enter source control.** No exceptions.
- All secrets live in environment variables or a secrets manager (Vault, AWS Secrets Manager, etc.).
- Local development uses `.env` files, which are in `.gitignore`.
- Production secrets are injected at runtime by the deployment platform.

### 9.2 Authentication and Authorization

- Even single-user deployments require authentication.
- The user is not root by default. Operations have least privilege.
- Every action affecting external systems or sensitive data is audit-logged.
- Authorization checks happen at the service boundary, not scattered through business logic.

### 9.3 Input Validation

- All external input is untrusted until validated.
- LLM outputs are treated as untrusted user input.
- Use Pydantic for structured input validation.
- Use schema validation for API responses.

### 9.4 Dependency Security

- All dependencies are pinned in `pyproject.toml` or `uv.lock`.
- Dependencies are scanned for known vulnerabilities before merge.
- No dependencies with known CVEs are permitted in production.
- Prefer well-maintained, widely-used libraries over niche alternatives.

### 9.5 Data Protection

- Encryption at rest for all persistent data.
- Encryption in transit for all network communication.
- Backups are encrypted and stored separately from runtime infrastructure.
- Data retention policies are configurable per data class.

---

## 10. Performance Expectations

### 10.1 General Rules

- **Do not optimize without measurement.** Premature optimization is a source of complexity.
- **Profile before optimizing.** Use `cProfile`, `py-spy`, or similar tools.
- **Optimize hot paths, not everything.** 80% of execution time is spent in 20% of code.

### 10.2 Trading-Specific Performance

Trading execution paths may have elevated performance requirements:
- Latency targets must be documented in the Trading module ADR.
- Performance optimizations require benchmarks proving improvement.
- Safety checks are never removed for performance.

### 10.3 Resource Limits

- Set explicit resource limits: memory, CPU, file descriptors, network connections.
- Timeouts must be set on all external I/O operations.
- Circuit breakers must be used for external service calls.

### 10.4 Async vs. Sync

- The kernel is sync-first for simplicity.
- I/O-bound operations (network calls, database queries) should use async patterns where beneficial.
- CPU-bound operations should use thread pools or process pools.
- Mixing sync and async code must be done through explicit bridges, not ad-hoc.

---

## 11. File and Module Organization

### 11.1 Module Size

- **Target:** less-than-or-equal 500 lines per module.
- **Hard limit:** 1000 lines.
- Exceeding 500 lines suggests the module should be split into a package.

### 11.2 Package Structure

```
package_name/
    __init__.py          # Public API exports only
    _internal.py         # Private implementation (leading underscore)
    interface.py         # Public interfaces and protocols
    models.py            # Data models and schemas
    utils.py             # Package-specific utilities (keep minimal)
    tests/
        test_public.py   # Tests for public API
        test_internal.py # Tests for internal logic
```

### 11.3 __init__.py Rules

- `__init__.py` should contain only imports that form the public API.
- No implementation logic in `__init__.py`.
- No side effects in `__init__.py` (no logging setup, no configuration loading, no network calls).
- Use `__all__` to explicitly define the public API.

### 11.4 Test Organization

- Tests mirror the structure of the code they test.
- Test utilities (fixtures, factories, helpers) live in `tests/conftest.py` or `tests/factories.py`.
- No test code in production modules.
- No production code in test modules.

---

## 12. Future Scalability Guidelines

### 12.1 Horizontal Scalability

- The kernel and services are designed to be stateless where possible.
- State is stored in services (database, memory, cache), not in process memory.
- This enables future horizontal scaling without architectural redesign.

### 12.2 Plugin Architecture

- Services and applications register through the kernel's service registry.
- Future plugins will use the same registration mechanism.
- Plugin isolation (sandboxing) will be added when third-party plugins are supported.

### 12.3 Configuration Evolution

- Configuration is currently flat. Future evolution toward nested models is anticipated:
  ```
  settings.database.url
  settings.llm.provider
  settings.logging.level
  ```
- This evolution must preserve backward compatibility or provide a migration path.

### 12.4 Multi-Model Support

- The LLM service is designed to support multiple providers through a unified interface.
- Future additions (local models, fine-tuned models, vision models) plug into the same abstraction.

### 12.5 Observability Evolution

- Current logging is local and structured.
- Future evolution may include:
  - Metrics export (Prometheus, StatsD)
  - Distributed tracing (OpenTelemetry)
  - Centralized log aggregation
- These must be added as services, not baked into the kernel.

---

## 13. Compliance and Verification

### 13.1 Pre-Commit Checklist

Before any code is committed:

- [ ] `ruff check` passes
- [ ] `ruff format --check` passes
- [ ] `pyright` passes with zero errors
- [ ] `pytest` passes with zero failures
- [ ] New code has tests
- [ ] New code has docstrings
- [ ] No secrets in code
- [ ] No `TODO` or `FIXME` comments (use issues instead)
- [ ] No dead code or unused imports

### 13.2 Continuous Integration

CI pipeline (when implemented) must run:
1. Ruff lint and format check
2. Pyright type check
3. pytest with coverage reporting
4. Security scan (dependency vulnerabilities)
5. Integration tests (if applicable)

### 13.3 Code Review

All changes require review by the Implementation Lead (Kimi) or Chief Architect (ChatGPT).
Review checks:
- Architecture alignment
- Test coverage
- Type safety
- Security implications
- Performance implications

---

## 14. Glossary

| Term | Definition |
|------|------------|
| **Kernel** | The minimal irreducible runtime of Jarvis. Cannot be replaced without rebuilding the system. |
| **Service** | A reusable, domain-independent capability exposed through a stable interface. |
| **Application** | User-facing business logic built on services. The Trading platform is Application 1. |
| **Interface** | A versioned contract defining what a service or component provides. |
| **ADR** | Architecture Decision Record. Documents significant design choices. |
| **HIC** | Human-in-the-Loop. Requires explicit user approval before execution. |
| **Autonomy Level** | The degree of independence a capability has. See Constitution for levels 0-4. |

---

## 15. Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-07-24 | Kimi | Initial specification |

---

*This document is governed by the Jarvis Constitution v1.0. When this specification conflicts with the Constitution, the Constitution takes precedence. Amendments to this specification require approval from the Chief Architect.*
