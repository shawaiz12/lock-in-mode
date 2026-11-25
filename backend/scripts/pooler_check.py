"""The API behind a transaction pooler, the way Vercel reaches Supabase (ADR 0031).

    uv run python scripts/pooler_check.py http://127.0.0.1:8077 20

CI runs it with the API behind PgBouncer in transaction mode: few database connections,
handed to a different client after every transaction, no prepared statements. Run it
with the same POSTGRES_* settings as the API. Two parts:
1. Many users at once through the running API, each: guest sign-in, profile, safety
   screen, plan, then two full workouts (every set) and the health check.
2. The app's own engine keeping one connection for many transactions in a row (a
   request that commits, then reads). Each transaction may land on another database
   connection: a statement prepared in one isn't there in the next.
Any error response, dropped connection or database error fails the run (exit 1).
"""

import asyncio
import sys
from collections import Counter
from typing import Any

import httpx
from sqlalchemy import text

from lock_in_mode_api.core.db import engine

PROFILE = {
    "goal": "build_muscle",
    "level": "beginner",
    "location": "gym",
    "equipment": [],
    "limits": [],
    "days_per_week": 3,
    "minutes_per_session": 45,
    "obstacles": [],
}
SAFETY = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
PARTS = ("warm_up", "main", "finisher", "cool_down")


class Journey:
    def __init__(self, client: httpx.AsyncClient, failures: Counter[str]) -> None:
        self.client = client
        self.failures = failures
        self.requests = 0

    async def call(self, method: str, url: str, **kwargs: Any) -> Any:
        self.requests += 1
        response = await self.client.request(method, url, **kwargs)
        if response.status_code >= 400:
            route = "/".join(url.split("/")[:5])
            self.failures[f"{method} {route}: {response.status_code} {response.text[:80]}"] += 1
            raise RuntimeError("stop this user")
        return response.json()

    async def run(self, user: int) -> None:
        # Its own address per user, so the per-IP sign-in limit (ADR 0008) isn't the test.
        tokens = await self.call(
            "POST", "/api/v1/auth/guest", headers={"X-Forwarded-For": f"10.99.{user}.1"}
        )
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        await self.call("PUT", "/api/v1/me/profile", json=PROFILE, headers=auth)
        await self.call("POST", "/api/v1/me/safety-screen", json=SAFETY, headers=auth)
        await self.call("POST", "/api/v1/plans", json=None, headers=auth)
        for _ in range(2):
            await self.call("GET", "/api/v1/plans/current", headers=auth)
            await self.call("GET", "/api/v1/me", headers=auth)
            workout_id = (await self.call("GET", "/api/v1/plans/current/next", headers=auth))["id"]
            session = await self.call(
                "POST", "/api/v1/sessions", json={"workout_id": workout_id}, headers=auth
            )
            workout = await self.call("GET", f"/api/v1/workouts/{workout_id}", headers=auth)
            for exercise in (e for part in PARTS for e in workout[part]):
                for set_number in range(1, exercise["sets"] + 1):
                    if exercise["seconds"] is None:
                        body = {"reps": exercise["reps_min"] or 8}
                    else:
                        body = {"seconds": exercise["seconds"]}
                    url = f"/api/v1/sessions/{session['id']}/sets/{exercise['id']}/{set_number}"
                    await self.call("PUT", url, json=body, headers=auth)
            await self.call(
                "POST",
                f"/api/v1/sessions/{session['id']}/finish",
                json={"feedback": "just_right"},
                headers=auth,
            )
        await self.call("GET", "/health")


async def many_transactions_on_one_connection(worker: int, failures: Counter[str]) -> None:
    try:
        async with engine.connect() as connection:
            for n in range(30):
                await connection.execute(
                    text("SELECT count(*) FROM exercises WHERE name <> :name"),
                    {"name": f"check-{worker}-{n}"},
                )
                await connection.execute(text("SELECT id FROM exercises ORDER BY id LIMIT 1"))
                await connection.commit()
    except Exception as error:  # any database error is the finding
        failures[f"engine: {type(error).__name__}: {str(error)[:80]}"] += 1


async def main(base_url: str, users: int) -> int:
    failures: Counter[str] = Counter()
    journeys: list[Journey] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:

        async def one(user: int) -> None:
            journey = Journey(client, failures)
            journeys.append(journey)
            try:
                await journey.run(user)
            except RuntimeError:
                pass  # already counted
            except httpx.HTTPError as error:  # e.g. the server dropped the connection
                failures[f"{type(error).__name__}: {error}"] += 1

        await asyncio.gather(*(one(user) for user in range(users)))
    total = sum(journey.requests for journey in journeys)
    print(f"{users} users, {total} requests, {sum(failures.values())} failed")

    before = sum(failures.values())
    await asyncio.gather(*(many_transactions_on_one_connection(w, failures) for w in range(10)))
    await engine.dispose()
    print(f"10 connections x 30 transactions, {sum(failures.values()) - before} failed")
    for failure, count in failures.most_common(10):
        print(f"  {count:4d} x {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], int(sys.argv[2]))))
