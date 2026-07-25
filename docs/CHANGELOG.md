## [Unreleased]

### Fixed
- **Nested scope bug** — `Container` now maintains a per-thread scope stack,
  so nested scopes correctly restore the outer scope on inner exit.
- **Private method cross-module access** — `Scope.set_active_scope`,
  `Scope.clear_active_scope`, and `Scope.resolve_scoped` are now public
  package-internal APIs. Removed global `reportPrivateUsage = false` from
  `pyproject.toml`.
- **CircularDependencyError propagation** — `CircularDependencyError` is now
  re-raised immediately during constructor injection, rather than being caught
  and wrapped in `MissingDependencyError`.

### Changed
- **Container docstrings** — Updated `resolve()` docstring to accurately
  describe singleton creation via auto-wiring (was stale: claimed delegation
  to `Registry.resolve()`).
- **Registry docstrings** — Added prominent note that `Registry.resolve()`
  does not perform constructor injection.
- **pyproject.toml** — Added `[build-system]`, replaced explicit `packages`
  with `setuptools.packages.find`, removed platform-specific `pythonPath`.
- **Stability markers** — `Registry`, `Container`, and `Scope` now carry
  explicit "stable for Milestone 2 baseline" notes in class docstrings.

### Added
- **Edge case tests** — forward references, dataclasses, ABC subclasses,
  `*args`/`**kwargs` skipping, classes with no `__init__`, `Optional[T]`
  injection, nested scope restoration, `build()` on registered types.
- **`.gitignore`** — Standard Python ignore patterns.

---

## [0.2.0] - 2026-07-24

### Added
- **Dependency Injection Container** (`kernel/di/`)
  - `Container` — automatic constructor injection with type hints
  - `Scope` — scoped lifetime management via context manager
  - `CircularDependencyError`, `MissingDependencyError`, `UnresolvableTypeError`
  - Recursive dependency resolution
  - Circular dependency detection with descriptive error chains
  - Thread-safe concurrent resolution
  - Support for singleton, transient, and scoped lifetimes
  - Auto-wiring of unregistered concrete types
  - Optional parameter handling (`Optional[T]`, `T | None`)
  - Integration with existing Service Registry (no duplication)

- **Enhanced Service Registry** (`kernel/registry/`)
  - `Lifetime.SCOPED` lifetime policy
  - `Registry.create()` — bypass singleton cache for fresh instances
  - `Registry.get_descriptor()` — public descriptor access
  - `InvalidRegistrationError` — malformed registration detection

- **Integration Tests** (`kernel/tests/test_integration.py`)
  - Full-stack Registry + Container scenarios
  - Mixed lifetime resolution
  - Scope isolation validation

### Changed
- Milestone 1 Registry extended with scoped lifetime and `create()` method.
- No breaking changes to existing public APIs.

---

## [0.1.0] - 2026-07-24

### Added
- **Kernel Configuration Bootstrap** (`kernel/config/`)
  - `JarvisSettings` — Pydantic-based configuration model with env var and `.env` support
  - `Environment` — `StrEnum` for runtime tiers (development, staging, production)
  - `LogLevel` — `StrEnum` for standard Python logging levels with case-insensitive coercion
  - `load_settings()` — Factory function returning fresh instances (no singleton)
  - `SecretStr` for `LLM_API_KEY` to prevent accidental logging
  - `extra="forbid"` to catch configuration typos
  - Full test coverage: defaults, overrides, validation, missing fields, enum rejection

- **Service Registry** (`kernel/registry/`)
  - `Registry` class for storing and retrieving service registrations by interface type
  - `register()`, `resolve()`, `unregister()`, `contains()` operations
  - `DuplicateRegistrationError` and `ServiceNotFoundError` custom exceptions
  - `Lifetime.SINGLETON` and `Lifetime.TRANSIENT` policies
  - Factory and instance registration support
  - `ServiceDescriptor` immutable data model
  - Thread-safe operations
  - Full type hints and Google-style docstrings
  - Complete test coverage for all operations

- **Repository Infrastructure**
  - `pyproject.toml` — Project metadata, dependencies, Ruff and Pyright configuration
  - `README.md` — Project overview and quick start
  - `docs/governance/001_ENGINEERING_SPEC.md` — Comprehensive engineering specification
  - `docs/governance/PROJECT_BIBLE.md` — Product vision and direction
  - `.env.example` — Configuration template
  - `main.py` — Minimal entry point

### Architecture
- Layered architecture: Kernel -> Services -> Applications
- No module-level singletons (lifecycle managed by DI container in Milestone 2)
- Interface-first design with versioned contracts
- Separation of concerns: settings model (`settings.py`) vs. loading mechanics (`loader.py`)

### Quality
- Ruff: Clean (linting and formatting)
- Pyright: 0 errors, 0 warnings, 0 informations
- pytest: All tests passing
- Google-style docstrings throughout
- No TODOs, no placeholder code, no dead code

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.2.0 | 2026-07-24 | Kimi | Milestone 2 — Dependency Injection |
| 0.1.0 | 2026-07-24 | Kimi | Milestone 1 — Service Registry & Config Bootstrap |
