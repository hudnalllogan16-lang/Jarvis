"""Desktop window (decision D-017).

Opening Jarvis should feel like opening an application. With `pywebview` installed
(the ``desktop`` extra) the dashboard runs in a native window whose close button
quits Jarvis; without it, the default browser opens.

**Thread ownership is a platform constraint, not a design choice.** pywebview
requires the main thread — native GUI toolkits on Windows and macOS own the main
thread's message loop and refuse to run anywhere else. `webview.start()` raises
`WebViewException("pywebview must be run on a main thread")` if called from a
worker thread (finding M5-F6, found on first real hardware run).

So the ownership inverts from the obvious arrangement: **the window owns the main
thread and the asyncio event loop runs on a background thread**, not the reverse.
`jarvis/shell/launcher.py` implements that inversion; this module only exposes the
two operations it needs and is deliberately ignorant of everything else.

`JARVIS_HEADLESS=1` disables both window and browser, for servers and CI.
"""

from __future__ import annotations

import os
import socket
import time
import webbrowser

from jarvis.kernel.logging import get_logger

logger = get_logger(__name__)

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8000
"""Fallback used only when a caller omits ``port``. The launcher passes
`Settings().api_port` explicitly at every call below (D-026.2, so two lane
environments can each bind their own port) — this module stays ignorant of
*where* that number comes from, per the module docstring above."""


def _dashboard_url(port: int) -> str:
    return f"http://{DASHBOARD_HOST}:{port}"


def headless() -> bool:
    """Return whether window and browser opening are disabled."""
    return os.environ.get("JARVIS_HEADLESS", "") not in ("", "0", "false")


def window_available() -> bool:
    """Return whether a native window can be opened in this environment.

    Probes the optional dependency rather than assuming it, so the same command
    works with and without the ``desktop`` extra installed.
    """
    if headless():
        return False
    try:
        import webview  # noqa: F401 - optional dependency, probed at runtime  # pyright: ignore[reportUnusedImport]
    except ImportError:
        return False
    return True


def wait_for_dashboard(*, port: int = DASHBOARD_PORT, timeout: float = 30.0) -> bool:
    """Block until the dashboard's port accepts connections.

    Args:
        port: The port the dashboard is bound to (`Settings().api_port`).
        timeout: Seconds to wait before giving up.

    Returns:
        True once the port is bound, False on timeout.

    A TCP connect is used rather than an HTTP request or a uvicorn internal flag,
    because the question being asked is exactly "can something connect to this
    port yet" — and opening a window before the answer is yes shows the operator a
    browser error page as their first impression of the application.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            if probe.connect_ex((DASHBOARD_HOST, port)) == 0:
                return True
        time.sleep(0.25)
    return False


def run_window_blocking(*, port: int = DASHBOARD_PORT) -> None:
    """Open the native window and block until the operator closes it.

    MUST be called from the main thread. Returns when the window is closed, which
    the launcher treats as the signal to shut Jarvis down — closing the window
    quits the app, as in any desktop program.

    Args:
        port: The port the dashboard is bound to (`Settings().api_port`).
    """
    import webview

    # pywebview ships no py.typed / complete stubs; create_window's own signature
    # resolves to a partially Unknown type regardless of how it is called here.
    webview.create_window(  # pyright: ignore[reportUnknownMemberType]
        "Jarvis", _dashboard_url(port), width=1160, height=800
    )
    webview.start()


def open_browser(*, port: int = DASHBOARD_PORT) -> None:
    """Fallback: open the default browser to the dashboard.

    Args:
        port: The port the dashboard is bound to (`Settings().api_port`).
    """
    if headless():
        return
    try:
        webbrowser.open(_dashboard_url(port))
    except Exception:
        logger.info("couldn't open a browser; dashboard is at %s", _dashboard_url(port))
