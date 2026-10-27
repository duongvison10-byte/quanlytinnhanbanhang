import hashlib
import hmac
import json

import pytest

from app import create_app, storage


PAGE_ID = "1177978082066315"
APP_SECRET = "test-app-secret-not-a-real-credential"
VERIFY_TOKEN = "test-webhook-verification-token"


@pytest.fixture
def app(monkeypatch):
    instance = create_app(
        {
            "TESTING": True,
            "META_PAGE_ID": PAGE_ID,
            "META_APP_SECRET": APP_SECRET,
            "META_VERIFY_TOKEN": VERIFY_TOKEN,
        }
    )
    monkeypatch.setattr(storage, "database_ready", lambda: True)
    return instance


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def delivery():
    return {
        "object": "page",
        "entry": [
            {
                "id": PAGE_ID,
                "time": 1700000000000,
                "messaging": [
                    {
                        "sender": {"id": "test-customer"},
                        "recipient": {"id": PAGE_ID},
                        "timestamp": 1700000000000,
                        "message": {"mid": "test-message-1", "text": "Test message"},
                    }
                ],
            }
        ],
    }


@pytest.fixture
def persist_calls(monkeypatch):
    calls = []

    def persist(payload, page_id):
        calls.append((payload, page_id))
        return {"stored_events": 1, "duplicate_events": 0}

    monkeypatch.setattr(storage, "persist_webhook", persist)
    return calls


@pytest.fixture
def signed_post(client):
    def send(payload=None, *, raw=None, signature=None, content_type="application/json"):
        if raw is None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if signature is None:
            digest = hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            signature = "sha256=" + digest
        return client.post(
            "/webhook",
            data=raw,
            content_type=content_type,
            headers={"X-Hub-Signature-256": signature},
        )

    return send
