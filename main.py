"""Jarvis main entry point.

This module serves as the primary entry point for the Jarvis
personal AI operating system. It is intentionally minimal
until the CLI and bootstrap subsystems are implemented.
"""

from kernel.config import load_settings


def main() -> None:
    """Bootstrap and run Jarvis."""
    settings = load_settings()
    print(f"Jarvis {settings.APP_VERSION} starting...")
    print(f"Environment: {settings.ENVIRONMENT}")


if __name__ == "__main__":
    main()
