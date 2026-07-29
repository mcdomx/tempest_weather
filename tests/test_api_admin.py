"""Tests for the /admin/metrics endpoint and the sd_notify watchdog helper."""

from fastapi.testclient import TestClient

from app.api import _sd_notify, app

client = TestClient(app)


def test_admin_metrics_returns_expected_shape():
    resp = client.get("/admin/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "subscribers" in body
    assert isinstance(body["threads"], int)
    assert isinstance(body["listener_thread_alive"], bool)
    assert isinstance(body["rss_kb"], int)


def test_sd_notify_is_noop_without_notify_socket(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    _sd_notify("READY=1")  # must not raise
