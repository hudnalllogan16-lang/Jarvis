"""The vendored fonts actually serve through the app, not just exist on disk
(M8-11, M8-F21 closes).

`tests/test_design_system.py` covers the static-analysis half — the link is
present, ordered ahead of `tokens.css`, and every asset `index.html`
references exists as a file. None of that proves a browser asking this
server for `/static/fonts.css` or one of its `@font-face` `src` URLs gets
real bytes back rather than a 404 hidden behind a passing file-exists check
(`StaticFiles`' mount path, a typo in `fonts.css`'s own relative `url(...)`,
or a font file excluded from what actually ships). These tests go through the
real ASGI app — the same one `jarvis.api.server` runs — so a broken mount or
a dangling reference fails here the way it would in a browser.

Rendering — the computed `font-family` an operator's browser actually
resolves for the display/body/data roles — is a browser property no
server-side test can observe; that half is verified live (see the packet
report) via a running instance and `document.fonts`/`getComputedStyle`.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from jarvis.api.app import create_app
from jarvis.kernel.config import LLMSettings, Settings
from jarvis.kernel.container import PlatformKernel
from jarvis.persistence.models import Base

STATIC_DIR = pathlib.Path("jarvis/api/static")
FONTS_CSS = STATIC_DIR / "fonts.css"

THE_THREE_FAMILIES = ("Bricolage Grotesque", "IBM Plex Sans", "IBM Plex Mono")


class _NoProvider:
    """No test here calls a model; this makes that an assertion."""

    @property
    def name(self) -> str:
        return "stub"

    async def complete(self, request: object) -> object:
        raise AssertionError("this surface never calls a model")

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    kernel = PlatformKernel(  # type: ignore[call-arg]
        Settings(llm=LLMSettings(model="stub-model"), _env_file=None),  # type: ignore[call-arg]
        engine=engine,
        provider=_NoProvider(),
    )
    transport = httpx.ASGITransport(app=create_app(kernel))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await kernel.aclose()


def _referenced_font_files() -> list[str]:
    """Every font URL `fonts.css` itself references via `url(...)`, relative
    to `jarvis/api/static/` (`fonts.css`'s own location) — each already reads
    ``fonts/<file>.woff2``, so this is also the path segment the `/static`
    mount serves it at."""
    css = FONTS_CSS.read_text(encoding="utf-8")
    refs = sorted(set(re.findall(r"url\(([^)]+)\)", css)))
    assert refs, "fonts.css references no font files — did the declarations move?"
    return refs


async def test_fonts_css_itself_serves(api: httpx.AsyncClient) -> None:
    res = await api.get("/static/fonts.css")
    assert res.status_code == 200
    assert res.content == FONTS_CSS.read_bytes(), "served bytes must match the vendored file"


async def test_every_family_is_declared_in_the_served_stylesheet(api: httpx.AsyncClient) -> None:
    """The three families this packet exists to hook up, by name, in the
    bytes actually served — not merely present somewhere in the repo."""
    res = await api.get("/static/fonts.css")
    for family in THE_THREE_FAMILIES:
        assert f"'{family}'" in res.text, f"{family} is not declared in the served fonts.css"


async def test_every_referenced_woff2_file_serves_real_bytes(api: httpx.AsyncClient) -> None:
    """Each `@font-face src` in `fonts.css` must resolve to a real, non-empty
    file through the same `/static` mount the browser uses — a relative
    `url(...)` typo or a binary left out of the vendored set would pass a
    file-exists check on the wrong path and 404 silently in a browser.
    """
    for ref in _referenced_font_files():
        on_disk = STATIC_DIR / ref
        assert on_disk.exists(), f"fonts.css references {ref!r}, which is not vendored on disk"

        res = await api.get(f"/static/{ref}")
        assert res.status_code == 200, f"{ref} did not serve (status {res.status_code})"
        assert res.content == on_disk.read_bytes()
        assert len(res.content) > 1000, f"{ref} served suspiciously few bytes: {len(res.content)}"


async def test_index_page_links_fonts_css_and_it_resolves(api: httpx.AsyncClient) -> None:
    """The link `index.html` ships resolves through the live app, ahead of
    tokens.css — the ordering half is pinned statically in
    `test_design_system.py`; this is the same claim, fetched for real."""
    page = await api.get("/")
    assert page.status_code == 200
    hrefs = re.findall(r'href="(/static/[^"]+\.css)"', page.text)
    assert hrefs and hrefs[0] == "/static/fonts.css", (
        "fonts.css must be the first stylesheet the served page links"
    )

    css = await api.get(hrefs[0])
    assert css.status_code == 200
