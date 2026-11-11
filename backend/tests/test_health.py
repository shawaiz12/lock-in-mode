from httpx import AsyncClient


async def test_health_returns_200_when_database_is_up(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200