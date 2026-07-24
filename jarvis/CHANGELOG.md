## [Unreleased]

### Added
- `docs/governance/001_ENGINEERING_SPEC.md` — Comprehensive engineering specification governing all future development.
- `CHANGELOG.md` — Project changelog for tracking changes across milestones.

### Changed
- **Engineering Specification v1.1** — Three additive architectural updates:
  - **Section 2.5: Architectural Invariants** — Permanent project rules governing AI Provider Independence, Incremental Development, Dependency Direction, Interface-First Design, and Extensibility.
  - **Relaxed /shared rule** — Changed from absolute prohibition to guidance: shared packages allowed only for genuine cross-cutting concerns, with emphasis on placing code in the narrowest owning layer.
  - **Enhanced Section 7.3: Architecture Decision Records** — Added full ADR format (Problem, Decision, Alternatives, Rationale, Consequences), lifecycle states (Proposed, Accepted, Superseded, Rejected), and example ADRs for future topics (DI, Event Bus, Provider Abstraction, Memory, Trading Engine).

---

## [1.0.0-milestone-1] - 2026-07-24

### Added
- **Service Registry** (`kernel/registry/`)
  - `ServiceRegistry` — Thread-safe registry supporting singleton and transient lifetimes
  - `register_singleton()` — Register shared instance or lazy-instantiated class
  - `register_singleton_factory()` — Register singleton via callable factory (lazy invocation, result cached)
  - `register_transient()` — Register factory class, new instance per resolve
  - `register_transient_factory()` — Register transient via callable factory (invoked every resolve)
  - `replace_singleton()` / `replace_singleton_factory()` — Explicit replacement of singleton registrations
  - `replace_transient()` / `replace_transient_factory()` — Explicit replacement of transient registrations
  - `resolve()` — Retrieve implementation by interface with correct lifetime semantics
  - `unregister()` / `contains()` / `clear()` / `len()` — Registry operations
  - `ServiceDescriptor` — Immutable frozen dataclass with slots for service metadata
  - `Lifetime` — `StrEnum` for singleton vs. transient
  - Exception hierarchy: `RegistryError` -> `DuplicateRegistrationError`, `ServiceNotFoundError`, `InvalidRegistrationError`
  - Thread safety via `threading.RLock` on all public methods
  - Lazy singleton instantiation under lock to prevent race conditions
  - Factory exception handling: failed singleton factories are retried on next resolve (not cached)
  - 65 unit tests covering: singleton behaviour, transient behaviour, duplicate detection, explicit replacement, missing services, registry operations, thread safety (concurrent resolution, registration races, mixed access), descriptor immutability, lifetime enum, exception hierarchy, singleton factories, transient factories, factory replacement, factory thread safety, factory exception behaviour

### Architecture
- No constructor injection (future milestone)
- No dependency graph resolution (future milestone)
- No external dependencies (stdlib only)
- Interface-first: services register under abstract interfaces/protocols
- Descriptors are immutable; singletons cached separately to support replacement

### Quality
- Ruff: Clean (linting and formatting)
- Pyright: 0 errors, 0 warnings, 0 informations
- pytest: 37/37 tests passing
- Google-style docstrings throughout
- No TODOs, no placeholder code, no dead code

---

## [1.0.0-milestone-1a] - 2026-07-24

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
  - Full type hints and Google-style docstrings
  - Complete test coverage for all operations

- **Repository Infrastructure**
  - `pyproject.toml` — Project metadata, dependencies, Ruff and Pyright configuration
  - `README.md` — Project overview and quick start
  - `PROJECT_BIBLE.md` — Engineering source of truth
  - `.env.example` — Configuration template
  - `main.py` — Minimal entry point

### Architecture
- Layered architecture: Kernel -> Services -> Applications
- No module-level singletons (lifecycle deferred to future DI container)
- Interface-first design with versioned contracts
- Separation of concerns: settings model (`settings.py`) vs. loading mechanics (`loader.py`)

### Quality
- Ruff: Clean (linting and formatting)
- Pyright: 0 errors, 0 warnings, 0 informations
- pytest: 22/22 tests passing
- Google-style docstrings throughout
- No TODOs, no placeholder code, no dead code

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-07-24 | Kimi | Engineering Specification v1.1 — Architectural Invariants, relaxed /shared rule, enhanced ADR policy |
| 2026-07-24 | Kimi | Initial changelog documenting Milestone 1A and governance spec |
