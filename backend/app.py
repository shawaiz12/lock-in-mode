"""Vercel's way into the API (ADR 0031).

Vercel looks for a FastAPI object called `app` in a file like this one and serves every
request with it. Locally and in Docker nothing uses this file: uvicorn loads
`lock_in_mode_api.main:app` directly.
"""

import sys
from pathlib import Path

# The code lives in src/ ("src layout"). uv installs it as a package, so it's importable
# anyway; this line only makes sure of it, whatever way Vercel installs the project.
_SRC = str(Path(__file__).resolve().parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lock_in_mode_api.main import app  # noqa: E402

__all__ = ["app"]
