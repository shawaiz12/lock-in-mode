"""The waitlist page at / (ADR 0037): served with its settings, locked down, honest."""

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.main import app
from lock_in_mode_api.web import site

STATIC = site.STATIC_DIR


async def _page(client: AsyncClient) -> str:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    return response.text


async def test_the_page_shows_the_offer_the_top_spots_and_the_launch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_founding_discount_percent", 40)
    monkeypatch.setattr(settings, "waitlist_top_spots", 25)
    monkeypatch.setattr(settings, "waitlist_launch_label", "January 2027")

    page = await _page(client)

    assert "40% off your first year of Pro" in page
    assert "top 25" in page
    assert "Top 25" in page
    assert "Launching January 2027" in page
    assert "$" not in page  # every placeholder filled


async def test_no_discount_means_no_offer_anywhere(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_founding_discount_percent", 0)

    page = await _page(client)

    assert "Founding" not in page
    assert "% off" not in page


async def test_the_launch_label_is_escaped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_launch_label", "<b>soon</b>")

    page = await _page(client)

    assert "<b>soon</b>" not in page
    assert "&lt;b&gt;soon&lt;/b&gt;" in page


async def test_the_page_is_locked_down(client: AsyncClient) -> None:
    response = await client.get("/")

    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    # Nothing on the page comes from another site (no trackers, no font CDNs).
    assert not re.search(r'(src|href)="https?://(?!www\.(tiktok|instagram)\.com)', response.text)
    assert "<script>" not in response.text  # no inline script (the CSP would block it)
    assert " style=" not in response.text


async def test_the_preview_image_link_is_https_when_hosted(client: AsyncClient) -> None:
    hosted = await client.get("/", headers={"host": "lockinmode.app"})
    local = await client.get("/")

    assert 'content="https://lockinmode.app/static/og.png"' in hosted.text
    assert 'content="http://test/static/og.png"' in local.text


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("site.css", "text/css"),
        ("site.js", "javascript"),
        ("icon.svg", "image/svg+xml"),
        ("og.png", "image/png"),
        ("fonts/rubik-800.woff2", "font/woff2"),
    ],
)
async def test_the_page_files_are_served_and_cached(
    client: AsyncClient, path: str, kind: str
) -> None:
    response = await client.get(f"/static/{path}")

    assert response.status_code == 200
    assert kind in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=86400"


async def test_a_missing_file_is_a_problem_document(client: AsyncClient) -> None:
    response = await client.get("/static/nope.js")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_every_file_the_page_asks_for_exists() -> None:
    page = (site.HERE / "page.html").read_text()
    css = (STATIC / "site.css").read_text()
    wanted = re.findall(r'"/static/([^"?]+)', page) + re.findall(r'url\("/static/([^"]+)"\)', css)

    assert wanted
    assert [p for p in wanted if not (STATIC / p).is_file()] == []


def test_the_font_licence_ships_with_the_fonts() -> None:
    assert "SIL Open Font License" in (STATIC / "fonts" / "OFL.txt").read_text()


@pytest.mark.parametrize("file", ["page.html", "static/site.js"])
def test_the_copy_has_no_em_dashes(file: str) -> None:
    """House style for anything people read (marketing notes, ig-human)."""
    assert "—" not in (site.HERE / file).read_text()


def test_the_page_says_nothing_the_app_cant_back_up() -> None:
    """Promises on the page must match what's built (build lessons). A promised split by
    days alone, or "every workout hits every head", would not be true."""
    text = Path(site.HERE / "page.html").read_text().lower()

    assert "built to train every one" in text  # what the templates do; not "every workout"
    assert "every workout hits" not in text
    assert "weekly streak" in text  # the streak is weekly (ADR 0034), never daily
    assert "daily streak" not in text


def test_the_page_is_not_in_the_api_docs() -> None:
    paths = app.openapi()["paths"]

    assert "/" not in paths
    assert "/api/v1/waitlist" in paths
