import io
import json
import urllib.error

import pytest

from app import meta

from conftest import PAGE_ID


def test_explicit_reply_uses_page_endpoint_and_response_message_type(app, monkeypatch):
    app.config["META_PAGE_ACCESS_TOKEN"] = "fake-test-token"
    calls = []

    def send(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps({"message_id": "test-message-id"}).encode())

    monkeypatch.setattr(meta.urllib.request, "urlopen", send)
    with app.app_context():
        response = meta.send_message("123456789", "Tư vấn thử nghiệm")
    assert response["message_id"] == "test-message-id"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == f"https://graph.facebook.com/v26.0/{PAGE_ID}/messages"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer fake-test-token"
    assert "fake-test-token" not in request.full_url
    assert timeout == 10
    assert json.loads(request.data) == {
        "recipient": {"id": "123456789"},
        "messaging_type": "RESPONSE",
        "message": {"text": "Tư vấn thử nghiệm"},
    }


@pytest.mark.parametrize(
    "recipient,text",
    [("not-numeric", "hello"), ("1234", ""), ("1234", "x" * 2001)],
)
def test_invalid_reply_never_reaches_network(app, monkeypatch, recipient, text):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid input must not reach the network")

    monkeypatch.setattr(meta.urllib.request, "urlopen", unexpected)
    with app.app_context(), pytest.raises(ValueError):
        meta.send_message(recipient, text)


def test_unconfigured_token_does_not_send(app, monkeypatch):
    app.config["META_PAGE_ACCESS_TOKEN"] = ""

    def unexpected(*args, **kwargs):
        pytest.fail("Missing credentials must not reach the network")

    monkeypatch.setattr(meta.urllib.request, "urlopen", unexpected)
    with app.app_context(), pytest.raises(ValueError, match="not configured"):
        meta.send_message("1234", "hello")


def test_meta_errors_do_not_echo_credential_or_remote_message(app, monkeypatch):
    credential = "fake-private-credential"
    app.config["META_PAGE_ACCESS_TOKEN"] = credential

    def rejected(*args, **kwargs):
        error = {"error": {"code": 190, "message": "sensitive remote message " + credential}}
        raise urllib.error.HTTPError(
            "https://graph.facebook.com/", 400, "Bad Request", {},
            io.BytesIO(json.dumps(error).encode()),
        )

    monkeypatch.setattr(meta.urllib.request, "urlopen", rejected)
    with app.app_context(), pytest.raises(meta.MetaAPIError) as failure:
        meta.send_message("1234", "hello")
    assert "HTTP 400" in str(failure.value)
    assert "190" in str(failure.value)
    assert credential not in str(failure.value)
    assert "sensitive remote message" not in str(failure.value)


def test_network_failure_is_reported_without_raw_exception(app, monkeypatch):
    app.config["META_PAGE_ACCESS_TOKEN"] = "fake-test-token"

    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("private transport details")

    monkeypatch.setattr(meta.urllib.request, "urlopen", unavailable)
    with app.app_context(), pytest.raises(meta.MetaAPIError) as failure:
        meta.send_message("1234", "hello")
    assert str(failure.value) == "Could not reach Meta."
