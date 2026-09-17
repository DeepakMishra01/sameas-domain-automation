import httpx
import pytest

from apps.api.main import app


@pytest.mark.asyncio
async def test_application_starts_and_health_works() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "dere"
