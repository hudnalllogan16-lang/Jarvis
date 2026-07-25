"""Versioned interfaces and protocols for the Jarvis kernel.

All major subsystems begin with a versioned interface. Implementations
come later and must satisfy the published contract.
"""

from kernel.interfaces.protocols import Disposable, Initializable

__all__ = [
    "Disposable",
    "Initializable",
]
