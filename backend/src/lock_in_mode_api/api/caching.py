"""Data saver: ETag + 304 Not Modified (ADR 0013).

The response gets a fingerprint of its body (the ETag). The app keeps the body and sends
the fingerprint back in `If-None-Match`; if nothing changed, the answer is an empty 304
and the app reuses what it has. The server still does the work. The phone doesn't
download it again, which is what matters on mobile data.
"""

import hashlib
from typing import Any

from fastapi import Request, Response, status
from pydantic import BaseModel

# private: answers depend on the user (cautions), so shared caches must not keep them.
# no-cache: the app may keep the body but must ask (with If-None-Match) before reusing it.
CACHE_CONTROL = "private, no-cache"

NOT_MODIFIED_DOC: dict[int | str, dict[str, Any]] = {
    status.HTTP_304_NOT_MODIFIED: {"description": "Not modified: reuse your copy"}
}


def _etag(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    # A list like: "abc", W/"def". Weak tags compare equal to strong ones for GET.
    sent = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return etag in sent


def json_with_etag(request: Request, payload: BaseModel) -> Response:
    body = payload.model_dump_json().encode()
    etag = _etag(body)
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL, "Vary": "Authorization"}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
