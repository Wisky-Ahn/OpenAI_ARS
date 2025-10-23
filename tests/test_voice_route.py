"""Twilio 음성 라우트에 대한 테스트 케이스를 제공합니다."""

import importlib

from fastapi.testclient import TestClient


def test_handle_incoming_call_returns_twi_ml(monkeypatch):
    """Twilio 콜 요청 시 올바른 TwiML이 반환되는지 검증합니다."""

    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_token")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SKXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_STREAM_ENDPOINT", "wss://example.com/twilio/stream")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://example.com")

    app_module = importlib.import_module("app.main")
    importlib.reload(app_module)
    app = app_module.create_app()
    client = TestClient(app)

    response = client.post("/twilio/voice")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert "<Connect>" in response.text
    assert "<Stream" in response.text


