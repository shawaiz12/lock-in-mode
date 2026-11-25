"""`python -m lock_in_mode_api.cleanup`: erase due accounts and lost guests once, then exit.

On Vercel (ADR 0031) the API only runs while it answers a request, so the hourly cleanup
inside the API (ADR 0024) can't run there. GitHub Actions runs this every hour instead
(.github/workflows/cleanup.yml). A failure exits with an error, so the run shows red and
GitHub emails you; the next hour tries again.
"""

import asyncio
import logging

from lock_in_mode_api.core.db import engine
from lock_in_mode_api.services.account import cleanup_once


async def main() -> None:
    try:
        erased, lost = await cleanup_once()
    finally:
        await engine.dispose()
    print(f"Account cleanup: erased {erased} account(s) and {lost} lost guest(s)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
