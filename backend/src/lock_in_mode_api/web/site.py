"""The waitlist page at / (ADR 0037), served by the API itself.

Same address as the API, so the page's calls to /api/v1/waitlist need no CORS, and one
deploy ships both. The HTML is one template; everything it promises (the founding offer,
the top-of-line invites, the launch month) comes from settings, so a change of plan is a
setting, not an edit to the page.

.NET: like an ASP.NET Core Razor Page in the same app as the API, with UseStaticFiles for
the css, js and fonts.
"""

import html
import mimetypes
from functools import cache
from pathlib import Path
from string import Template

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from lock_in_mode_api.core.config import settings

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"

# The content types the page's files are served with, fixed here: Python asks the system,
# and Windows can answer "application/octet-stream" for .woff2 or "text/plain" for .js
# (a browser refuses to run a script sent as text/plain, given nosniff). Linux, where the
# API runs, already agrees; this makes every machine agree.
for _type, _ext in (
    ("text/css", ".css"),
    ("text/javascript", ".js"),
    ("image/svg+xml", ".svg"),
    ("image/png", ".png"),
    ("font/woff2", ".woff2"),
):
    mimetypes.add_type(_type, _ext)

# The browser may only load what this server sends: no third-party scripts, fonts or
# trackers, no framing (clickjacking), forms only post here.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "test"}

router = APIRouter(include_in_schema=False)


@cache
def _template() -> Template:
    return Template((HERE / "page.html").read_text(encoding="utf-8"))


def _offer_parts() -> dict[str, str]:
    """The founding-member offer in the four places it shows, or nothing at all when the
    discount is 0 (the page never mentions an offer that isn't there)."""
    pct = settings.waitlist_founding_discount_percent
    top = settings.waitlist_top_spots
    if pct == 0:
        return {"offer_strip": "", "founding_note": "", "perks_section": "", "faq_discount": ""}
    return {
        "offer_strip": (
            '<p class="offer"><strong>Founding member:</strong> '
            f"{pct}% off your first year of Pro, plus a Founding badge in the app. "
            "Only for people who join before launch.</p>"
        ),
        "founding_note": (
            '<p class="founding">Founding member: your '
            f"{pct}% off the first year of Pro is saved. Your launch email says how to "
            "claim it.</p>"
        ),
        "perks_section": (
            '<section class="section perks"><h2>Founding member perks</h2>'
            '<ul class="perk-list">'
            f'<li class="card gold"><strong>{pct}% off</strong>'
            "<span>your first year of Pro</span></li>"
            '<li class="card"><strong>Founding badge</strong>'
            "<span>in the app, for good</span></li>"
            f'<li class="card"><strong>Top {top}</strong>'
            "<span>get an Android test invite before launch</span></li>"
            "</ul>"
            '<p class="fine">Only for people who join before launch. Pro\'s price is '
            "announced at launch.</p></section>"
        ),
        "faq_discount": f" Founding members get {pct}% off the first year.",
    }


def _origin(request: Request) -> str:
    """For the link-preview image, which needs a full address. Hosted, it's always https
    (the platform's proxy talks plain http to us, so the request itself can't tell)."""
    host = request.url.netloc
    scheme = request.url.scheme if request.url.hostname in LOCAL_HOSTS else "https"
    return f"{scheme}://{host}"


def render_page(request: Request) -> str:
    return _template().substitute(
        origin=html.escape(_origin(request), quote=True),
        version=html.escape(settings.app_version, quote=True),
        launch=html.escape(settings.waitlist_launch_label),
        top=str(settings.waitlist_top_spots),
        **_offer_parts(),
    )


@router.get("/", response_class=HTMLResponse)
async def waitlist_page(request: Request) -> HTMLResponse:
    return HTMLResponse(
        render_page(request),
        headers={**SECURITY_HEADERS, "Cache-Control": "public, max-age=300"},
    )


class CachedStatic(StaticFiles):
    """css and js change with each deploy (the page asks for ?v=<commit>), fonts and
    images almost never: a day in the browser for all of them."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


static_files = CachedStatic(directory=STATIC_DIR)
