"""API server entrypoint."""

from __future__ import annotations

import asyncio

import uvicorn

from jarvis.api.app import create_app
from jarvis.kernel.config import Settings
from jarvis.kernel.container import PlatformKernel


async def _run() -> None:
    """Build the kernel and serve the API on a single event loop (M6-F7).

    The kernel's engine binds its asyncpg connections to whichever loop is
    running the first time they are used. The previous shape called
    ``asyncio.run(kernel.ensure_builtin_types())`` — which opens a loop, uses
    the pool, then closes that loop — and afterwards ``uvicorn.run(...)``,
    which opens a second, unrelated loop to serve. Every DB route then ran on
    a loop the pool's connections did not belong to and 500'd. The launcher
    (`jarvis/shell/launcher.py::launch`) never hits this because setup and
    serving both run under one `asyncio.run()` call; mirrored here.
    """
    settings = Settings()  # type: ignore[call-arg]
    kernel = PlatformKernel(settings)
    await kernel.ensure_builtin_types()
    server = uvicorn.Server(
        uvicorn.Config(create_app(kernel), host="127.0.0.1", port=settings.api_port)
    )
    try:
        await server.serve()
    finally:
        await kernel.aclose()


def main() -> None:
    """Run the operator API and dashboard on `Settings().api_port` (default 8000)."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
