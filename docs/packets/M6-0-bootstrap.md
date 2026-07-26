## Packet M6-0: establish the real test baseline

**Agent:** test-engineer   **Model:** sonnet — high gate coverage (the suite is itself the
gate), low blast radius, trivially reversible. Escalate up only if a failure turns out to be
an architectural disagreement rather than a defect.

**Objective**
Determine which of the ~229 written tests actually pass, fix what is fixable without changing
behaviour, and report an accurate baseline.

**Context you need**
This suite has never been executed. Every prior session ran without network access or
third-party packages, so tests were written against SQLAlchemy, pydantic, FastAPI, and
Temporal without ever importing them. Expect import errors, fixture mismatches, and assertion
drift. This is known and disclosed — you are not looking at a broken architecture, you are
paying down a documented debt.

`scripts/gates.sh` exit codes are a contract: `0` pass, `2` a gate ran and failed, `3` a gate
could not run. In this environment you should be able to reach `0` or `2`; a `3` means the
toolchain isn't working and that is your finding.

**Files in scope**
Read first:
- `pyproject.toml` — dependency and tool configuration
- `tests/conftest.py` — the fixtures everything depends on. If this is wrong, everything fails.
- `scripts/gates.sh` — what you must make pass

You may edit anything under `tests/`. You may edit `pyproject.toml` only to correct a
dependency or tool-configuration error.

**You may not** edit anything under `jarvis/` or `migrations/`. If a test fails because the
*implementation* is wrong, that is a finding to report, not a fix to make — reporting it is
the valuable outcome, and the fix is a separate packet with a different agent.

**Acceptance criteria**
- [ ] `uv sync --all-extras` completes; record any dependency resolution problems
- [ ] `uv run pytest -q` executes to completion (not necessarily green)
- [ ] Every failure classified as exactly one of: (a) test defect — fixed; (b) fixture or
      config defect — fixed; (c) implementation defect — reported, not fixed; (d) test asserts
      something the architecture doesn't guarantee — reported for the Manager to arbitrate
- [ ] `bash scripts/gates.sh` reports its true state
- [ ] Report gives exact counts: collected, passed, failed, errored, skipped

**Out of scope**
Adding new tests (later packets). Any change under `jarvis/`. Any performance work.
Reformatting files you didn't otherwise touch.

**Escalate instead of deciding if**
- A test and the implementation disagree about intended behaviour — one is wrong and deciding
  which is the Manager's call, not yours
- A fixture cannot be made correct without changing an interface in `jarvis/`
- More than about a quarter of tests fail for one shared root cause — stop and report the
  cause before grinding through symptoms
- Making a test pass would require weakening what it asserts
