#!/usr/bin/env bash
# Executable acceptance gates for Jarvis.
#
# Wired as a SubagentStop hook (.claude/settings.json) so no worker can report
# completion over failing gates, and runnable by hand before any merge decision.
#
# Two failure modes are deliberately distinguished, because conflating them is
# how a project ends up believing it verified something it didn't:
#
#   exit 2  A gate RAN and FAILED. Real defect. Blocks completion.
#   exit 3  A gate COULD NOT RUN (no uv, no network, missing deps). Structural
#           gates still run and must pass, but the full suite is unverified.
#
# A worker hitting exit 3 has NOT verified its work. It must say "gates degraded
# — full suite unexecuted" in its report. Claiming verification on a degraded run
# is the overclaiming this project treats as a finding (see M5-F5).
set -uo pipefail
cd "$(dirname "$0")/.."

LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

# ── Machine record ──────────────────────────────────────────────────────────
# Every run appends gate outcomes here. scripts/manifest.py assembles run
# manifests from these records, so the manifest reports what actually happened
# rather than what anyone claims happened. Nothing that reads this file trusts a
# coordinator's or worker's account of a gate.
RECORD_DIR=".jarvis-run"
mkdir -p "$RECORD_DIR"
RECORD="$RECORD_DIR/gate-$(date +%s%N).json"
GATES_JSON=""
TESTS_TOTAL=""

record_gate() {  # name, status
  local sep=""
  [ -n "$GATES_JSON" ] && sep=","
  GATES_JSON="${GATES_JSON}${sep}{\"name\":\"$1\",\"status\":\"$2\"}"
}

emit_record() {  # exit_code, note
  printf '{"timestamp":"%s","exit_code":%s,"note":"%s","tests":"%s","gates":[%s]}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "${TESTS_TOTAL}" "$GATES_JSON" > "$RECORD"
}

fail()    { record_gate "$2" "failed"; emit_record 2 "$1"
            echo "GATE FAILED: $1" >&2; tail -n 30 "$LOG" >&2; exit 2; }
degrade() { record_gate "full_suite" "degraded"; emit_record 3 "$1"
            echo "GATES DEGRADED: $1" >&2
            echo "  Structural gates passed; full suite UNEXECUTED." >&2; exit 3; }

# ── Gate 1: syntax. Always available, no dependencies. ──────────────────────
python3 -m compileall -q jarvis tests migrations >"$LOG" 2>&1 \
  || fail "syntax errors (compileall)" syntax
record_gate "syntax" "passed"

# ── Gate 2: structural invariants. Stdlib only, so these always run. ────────
# Layering, entrypoint purity, package/doc sync, and the §12.5 operator
# vocabulary check. These need no database, no network, no third-party packages —
# which is exactly why they are the ones that always execute.
python3 - >"$LOG" 2>&1 <<'PY' || fail "structural invariants" structural
import pathlib, re, sys, types, ast

pt = types.ModuleType("pytest")
class _M:
    def parametrize(self, *a, **k): return lambda f: f
pt.mark = _M()
sys.modules.setdefault("pytest", pt)
sys.path.insert(0, "tests")

from test_layering import (
    COMPOSITION_ROOTS, ENTRYPOINT_ROOTS, MILESTONE, _forward_imports, _package_of,
)

srcs = sorted(pathlib.Path("jarvis").rglob("*.py"))

bad = {str(p): sorted(_forward_imports(p)) for p in srcs
       if p not in COMPOSITION_ROOTS and _forward_imports(p)}
assert not bad, f"forward imports outside composition roots: {bad}"

for root in ENTRYPOINT_ROOTS:
    classes = [n.name for n in ast.walk(ast.parse(root.read_text()))
               if isinstance(n, ast.ClassDef)]
    assert not classes, f"{root} defines {classes}; entrypoints hold no logic"

pkgs = {_package_of(p) for p in srcs if len(p.relative_to("jarvis").parts) > 1}
missing = sorted(pkgs - set(MILESTONE))
assert not missing, f"packages with no milestone assignment: {missing}"

doc = pathlib.Path("docs/DEPENDENCIES.md").read_text()
undocumented = [p for p in MILESTONE if f"`{p}`" not in doc]
assert not undocumented, f"packages missing from the layering table: {undocumented}"

# Which files carry operator-facing copy — and the forbidden-term list itself
# — are defined ONCE, in tests/surface_sources.py, and imported by this gate
# and by the test modules asserting the same property. Before M8-2 each
# consumer re-derived the file list with its own regex over a single inline
# <script>; after the decomposition that regex would have matched nothing and
# this gate would have passed VACUOUSLY. surface_sources asserts its inputs
# are non-empty, so an emptied, renamed or moved module set raises here
# instead of silently disabling the check. The term list itself was a second,
# separately-drifting copy until design PLUGIN-FRAMEWORK.md Part 6's M7-F12
# note (fifteen terms here vs. the test module's seventeen — this gate was
# missing "woken" and "business" and would have PASSED a violation the test
# below still failed on): both now import tests.surface_sources.FORBIDDEN.
import surface_sources

FORBIDDEN = surface_sources.FORBIDDEN

modules = surface_sources.script_paths()
assert len(modules) >= 2, f"S12.5 gate: expected the decomposed module set, found {modules}"

leaked = [t for t in FORBIDDEN if t in surface_sources.visible_text().lower()]
assert not leaked, f"S12.5: forbidden terms in dashboard markup: {leaked}"

leaked = [t for t in FORBIDDEN if t in surface_sources.script_literals().lower()]
assert not leaked, f"S12.5: forbidden terms in dashboard copy: {leaked}"

# The decomposition's own new failure mode: index.html now references its
# stylesheets and entry module by path. A typo there unstyles the entire
# surface without failing any other check, because the markup still parses and
# the server still serves it.
for ref in re.findall(r'(?:href|src)="(/static/[^"]+)"', surface_sources.markup()):
    target = pathlib.Path("jarvis/api") / ref.lstrip("/")
    assert target.exists(), f"index.html references a missing asset: {ref}"

print("structural invariants OK: layering, entrypoints, package/doc sync, S12.5, assets")
PY
record_gate "structural" "passed"

# ── Gate 3: full suite, linter, types. Needs a working toolchain. ───────────
if ! command -v uv >/dev/null 2>&1; then
  degrade "uv not installed"
fi

# uv existing is not uv working: it may be unable to fetch an interpreter or
# resolve dependencies offline. Probe first, so a toolchain problem is never
# reported as a passing test suite.
if ! uv run --frozen python -c "import sys" >"$LOG" 2>&1; then
  degrade "uv present but cannot run (offline, or interpreter unavailable)"
fi

uv run --frozen pytest -q >"$LOG" 2>&1 || fail "test suite" unit
TESTS=$(grep -oE '[0-9]+ passed' "$LOG" | head -1 || echo "count unavailable")
TESTS_TOTAL="${TESTS}"
record_gate "unit" "passed"

uv run --frozen ruff check jarvis tests >"$LOG" 2>&1 || fail "ruff" lint
uv run --frozen ruff format --check jarvis tests >"$LOG" 2>&1 || fail "ruff format" format
record_gate "lint" "passed"
record_gate "format" "passed"

if uv run --frozen pyright --version >/dev/null 2>&1; then
  uv run --frozen pyright jarvis >"$LOG" 2>&1 || fail "pyright" types
  record_gate "types" "passed"
fi

emit_record 0 "all gates passed"
echo "ALL GATES PASSED — ${TESTS}, ruff clean, structural invariants OK"
