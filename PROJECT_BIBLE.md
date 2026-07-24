# Jarvis Project Bible
Version: 1.0
Status: Active

---

# Mission

Jarvis is a personal AI Operating System focused on augmenting high-value decision making.

Version 1 is built around three applications:

- Trading
- Finance
- Projects

Everything else is optional and may be added later without modifying the core architecture.

---

# Core Philosophy

The kernel should remain small.
Business logic belongs inside applications.
Reusable functionality belongs inside services.
Applications should never depend directly on each other.
Every architectural decision should maximize:

- Simplicity
- Maintainability
- Extensibility
- Testability

---

# Repository Structure

```
apps/        # Business applications
services/    # Reusable capabilities
kernel/      # Core runtime (irreducible)
docker/      # Container definitions
docs/        # Documentation
scripts/     # Dev tools and migrations
tests/       # Integration and E2E tests
```

---

# Technology Stack

- Python 3.14
- uv (package manager)
- pytest (testing)
- Ruff (formatting and linting)
- Pyright (type checking)
- Pydantic (configuration and validation)
- PostgreSQL + SQLAlchemy 2 (database)
- FastAPI (API layer)
- LiteLLM (LLM routing)

---

# Current Roadmap

## Milestone 1: Bootstrap
- Configuration
- Service Registry
- Logging

## Milestone 2: Core Services
- LLM Integration
- Memory
- Tool Registry

## Milestone 3: Trading Intelligence

## Milestone 4: Finance

## Milestone 5: Projects

---

This document is the engineering source of truth.
Every implementation should follow it.
