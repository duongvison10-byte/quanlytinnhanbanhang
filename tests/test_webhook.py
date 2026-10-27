import copy
import json

import mysql.connector
import pytest

from app import storage

from conftest import PAGE_ID, VERIFY_TOKEN


def test_health_is_independent_of_database(client, monkeypatch):
    monkeypatch.setattr(storage, "database_ready", lambda: False)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_ready_requires_database_and_webhook_configuration(client):
    assert client.get("/readyz").status_code == 200


@pytest.mark.parametrize("missing", ["META_APP_SECRET", "META_VERIFY_TOKEN"])
def test_ready_rejects_missing_webhook_configuration(app, client, missing):
    app.config[missing] = ""
    assert client.get("/readyz").status_code == 503


def test_ready_rejects_unavailable_database(client, monkeypatch):
    monkeypatch.setattr(storage, "database_ready", lambda: False)
    assert client.get("/readyz").status_code == 503


def test_meta_verification_returns_exact_challenge(client):
    response = client.get(
        "/webhook",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1234567890",
        },
    )
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "1234567890"
    assert response.mimetype == "text/plain"


def test_meta_verification_rejects_wrong_token(client):
    response = client.get(
        "/webhook",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "1234567890",
        },
    )
    assert response.status_code == 403
    assert "wrong-token" not in response.get_data(as_text=True)


def test_meta_verification_rejects_unicode_token_without_server_error(client):
    response = client.get(
        "/webhook",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "mã-không-hợp-lệ",
            "hub.challenge": "1234567890",
        },
    )
    assert response.status_code == 403


def test_meta_verification_fails_closed_without_server_token(app, client):
    app.config["META_VERIFY_TOKEN"] = ""
    response = client.get(
        "/webhook",
        query_string={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"},
    )
    assert response.status_code == 503


def test_signed_message_is_persisted_before_acknowledgement(signed_post, delivery, persist_calls):
    response = signed_post(delivery)
    assert response.status_code == 200
    assert persist_calls == [(delivery, PAGE_ID)]


def test_signed_feed_comment_is_accepted(signed_post, persist_calls):
    payload = {
        "object": "page",
        "entry": [
            {
                "id": PAGE_ID,
                "time": 1700000000,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "test-post_test-comment",
                            "post_id": "test-post",
                            "message": "Test comment",
                            "created_time": 1700000000,
                        },
                    }
                ],
            }
        ],
    }
    assert signed_post(payload).status_code == 200
    assert persist_calls == [(payload, PAGE_ID)]


def test_unsigned_body_is_never_written(client, delivery, persist_calls):
    response = client.post("/webhook", json=delivery)
    assert response.status_code == 403
    assert persist_calls == []


@pytest.mark.parametrize("signature", ["sha256=" + "0" * 64, "sha1=" + "0" * 40, "not-a-signature"])
def test_wrong_or_malformed_signature_is_never_written(signed_post, delivery, persist_calls, signature):
    assert signed_post(delivery, signature=signature).status_code == 403
    assert persist_calls == []


def test_signature_covers_original_bytes_not_reserialized_json(signed_post, delivery, persist_calls):
    raw = json.dumps(delivery, indent=4).encode()
    assert signed_post(raw=raw).status_code == 200
    assert persist_calls == [(delivery, PAGE_ID)]


def test_tampered_signed_payload_is_rejected(client, delivery, persist_calls):
    import hashlib
    import hmac

    from conftest import APP_SECRET

    original = json.dumps(delivery).encode()
    signature = "sha256=" + hmac.new(APP_SECRET.encode(), original, hashlib.sha256).hexdigest()
    tampered = copy.deepcopy(delivery)
    tampered["entry"][0]["messaging"][0]["message"]["text"] = "Changed after signing"
    response = client.post(
        "/webhook", json=tampered, headers={"X-Hub-Signature-256": signature}
    )
    assert response.status_code == 403
    assert persist_calls == []


def test_missing_app_secret_rejects_post_without_persistence(app, signed_post, delivery, persist_calls):
    app.config["META_APP_SECRET"] = ""
    assert signed_post(delivery).status_code == 503
    assert persist_calls == []


@pytest.mark.parametrize("raw", [b"{", b"not json", b"null", b"[]"])
def test_valid_signature_does_not_make_malformed_payload_valid(signed_post, persist_calls, raw):
    assert signed_post(raw=raw).status_code == 400
    assert persist_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "instagram", "entry": []},
        {"object": "page", "entry": None},
        {"object": "page", "entry": {}},
        {"object": "page", "entry": [None]},
    ],
)
def test_invalid_page_delivery_shape_is_not_written(signed_post, persist_calls, payload):
    assert signed_post(payload).status_code == 400
    assert persist_calls == []


def test_delivery_for_other_page_is_not_written(signed_post, delivery, persist_calls):
    delivery["entry"][0]["id"] = "999999999"
    assert signed_post(delivery).status_code == 403
    assert persist_calls == []


def test_mixed_page_batch_is_rejected_as_a_whole(signed_post, delivery, persist_calls):
    foreign = copy.deepcopy(delivery["entry"][0])
    foreign["id"] = "999999999"
    delivery["entry"].append(foreign)
    assert signed_post(delivery).status_code == 403
    assert persist_calls == []


def test_database_failure_is_retryable_not_acknowledged(signed_post, delivery, monkeypatch):
    def fail(payload, page_id):
        raise mysql.connector.Error("simulated storage unavailable")

    monkeypatch.setattr(storage, "persist_webhook", fail)
    assert signed_post(delivery).status_code == 503


def test_duplicate_delivery_still_acknowledged(signed_post, delivery, monkeypatch):
    monkeypatch.setattr(
        storage,
        "persist_webhook",
        lambda payload, page_id: {"stored_events": 0, "duplicate_events": 1},
    )
    assert signed_post(delivery).status_code == 200


def test_oversized_payload_is_rejected_without_database_write(signed_post, persist_calls):
    response = signed_post(raw=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert persist_calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("sender", "not-an-object"),
        ("recipient", ["not-an-object"]),
        ("message.text", {"not": "text"}),
        ("message.mid", "x" * 256),
    ],
)
def test_invalid_nested_message_fields_are_rejected_before_storage(
    signed_post, delivery, persist_calls, field, value
):
    item = delivery["entry"][0]["messaging"][0]
    path = field.split(".")
    for part in path[:-1]:
        item = item[part]
    item[path[-1]] = value
    assert signed_post(delivery).status_code == 400
    assert persist_calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("from", "not-an-object"),
        ("message", ["not", "text"]),
        ("comment_id", "x" * 256),
    ],
)
def test_invalid_nested_comment_fields_are_rejected_before_storage(
    signed_post, persist_calls, field, value
):
    comment = {
        "item": "comment",
        "verb": "add",
        "comment_id": "test-post_test-comment",
        "post_id": "test-post",
        "from": {"id": "test-customer"},
        "message": "Test comment",
        "created_time": 1700000000,
    }
    comment[field] = value
    payload = {
        "object": "page",
        "entry": [{"id": PAGE_ID, "changes": [{"field": "feed", "value": comment}]}],
    }
    assert signed_post(payload).status_code == 400
    assert persist_calls == []
