"""Built-in business type catalog (spec §4; M8 design doc Part 2.1).

`BUILTIN_TYPES` used to live in `jarvis/kernel/container.py`, a composition
root — which made adding a type a composition-root edit and stood directly
against M8's own success criterion: a third type installable "with zero
composition-root edits". It lives here instead, next to the types it lists,
so that adding one is a one-line edit in this package (M5) and zero edits in
`container.py` (M8-F1's first half).

`container.py` still imports this tuple, but only as the *default* value it
hands `PlatformKernel`'s `builtin_types` parameter (design Part 2.2) — the
injected sequence, not this module global, is the platform's entire
type-extension path. A test, §4's future wizard-installable type, an
operator-uploaded type, or an M11 package loader all supply a different
sequence to the Kernel; none of them touches this file.
"""

from __future__ import annotations

from jarvis.businesses.affiliate import AFFILIATE
from jarvis.businesses.definition import BusinessTypeDefinition
from jarvis.businesses.finance import FINANCE

BUILTIN_TYPES: tuple[BusinessTypeDefinition, ...] = (AFFILIATE, FINANCE)
"""The business types every installation starts with (spec §13 Steps 1 and 3).

Adding a third built-in type is exactly this: import it and append it to the
tuple. Nothing in `container.py`, `ensure_builtin_types`, or the per-type
version gate needs to change (design Part 2.2)."""
