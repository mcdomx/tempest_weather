import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)

# Positional obs_st row matching OBS_ST_FIELDS order
MOCK_ROW = [1700000000, 0.5, 1.0, 2.0, 180, 3, 1013.0, 22.5, 60, 10000, 3.5, 200, 0.0, 0, 5, 0, 2.72, 1]

MOCK_OBS_RESP = {"obs": [MOCK_ROW, [r + 60 if i == 0 else r for i, r in enumerate(MOCK_ROW)]]}


@pytest.mark.asyncio
async def test_history_default_minutes():
    obs_resp = AsyncMock()
    obs_resp.raise_for_status = lambda: None
    obs_resp.json = lambda: MOCK_OBS_RESP

    with patch("app.cloud._device_id_cache", 1220679), \
         patch("app.cloud.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.get = AsyncMock(return_value=obs_resp)

        resp = client.get("/weather/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["minutes"] == 60
        assert body["count"] == 2
        obs = body["observations"][0]
        assert "air_temp_c" in obs
        assert obs["air_temp_c"] == 22.5
        assert "wind_avg_m_s" in obs
        assert "timestamp" in obs


@pytest.mark.asyncio
async def test_history_custom_minutes():
    obs_resp = AsyncMock()
    obs_resp.raise_for_status = lambda: None
    obs_resp.json = lambda: {"obs": []}

    with patch("app.cloud._device_id_cache", 1220679), \
         patch("app.cloud.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.get = AsyncMock(return_value=obs_resp)

        resp = client.get("/weather/history?minutes=30")
        assert resp.status_code == 200
        assert resp.json()["minutes"] == 30


def test_history_minutes_out_of_range():
    resp = client.get("/weather/history?minutes=0")
    assert resp.status_code == 422

    resp = client.get("/weather/history?minutes=1441")
    assert resp.status_code == 422
