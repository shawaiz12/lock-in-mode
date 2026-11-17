"""`python -m lock_in_mode_api.seed`: validate the seed file and load it into the database."""

import asyncio

from lock_in_mode_api.core.db import SessionLocal, engine
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library


async def main() -> None:
    library = load_library()  # fails loudly, before touching the database, if the file is bad
    try:
        async with SessionLocal() as session:
            report = await load_exercises(session, library)
    finally:
        await engine.dispose()
    print(f"Exercise library: {len(library.exercises)} in the seed file")
    print(report.summary())


if __name__ == "__main__":
    asyncio.run(main())
