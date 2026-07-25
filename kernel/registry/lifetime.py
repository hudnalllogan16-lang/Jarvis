"""Service lifetime definitions for the Jarvis Service Registry."""

from enum import StrEnum


class Lifetime(StrEnum):
    """Defines how long a registered service lives.

    Attributes:
        SINGLETON: One instance shared across all resolves.
        TRANSIENT: A new instance created on every resolve.
    """

    SINGLETON = "singleton"
    TRANSIENT = "transient"
