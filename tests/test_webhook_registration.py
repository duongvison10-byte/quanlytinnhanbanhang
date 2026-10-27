import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

import pytest


APP_ID = "29122218940802027"
PAGE_ID = "1177978082066315"
CALLBACK = "https://test-onboarding.trycloudflare.com/webhook"
FIELDS = "messages,messaging_postbacks,feed"


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200):
        if isinstance(body, dict):
            body = json.dumps(body)
        super().__init__(body.encode())
        self.status = status


@pytest.fixture
def registration(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "connect-meta-webhook.py"
    spec = importlib.util.spec_from_file_location("connect_meta_webhook_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", [str(path)])
    for name, value in {
        "META_APP_ID": APP_ID,
        "META_PAGE_ID": PAGE_ID,
        "META_APP_SECRET": "fake-app-secret",
        "META_PAGE_ACCESS_TOKEN": "fake-page-token",
        "META_VERIFY_TOKEN": "fake-verify-token",
    }.items():
        monkeypatch.setenv(name, value)
    local = tmp_path / ".local"
    local.mkdir()
    (local / "public-webhook-url").write_text(CALLBACK + "\n")
    original_umask = os.umask(0o077)
    os.umask(original_umask)
    try:
        yield module
    finally:
        os.umask(original_umask)


@pytest.fixture
def network(monkeypatch):
    def install(*, existing=None, ready_status=200, valid_challenge=True, callback=CALLBACK):
        calls = []

        def urlopen(request, timeout):
            if isinstance(request, urllib.request.Request):
                url = request.full_url
                method = request.get_method()
                data = urllib.parse.parse_qs(request.data.decode()) if request.data else {}
                authorization = request.get_header("Authorization")
            else:
                url = request
                method = "GET"
                data = {}
                authorization = None
            parsed = urllib.parse.urlsplit(url)
            calls.append({
                "url": url, "method": method, "parameters": data,
                "authorization": authorization,
            })
            if parsed.hostname == "graph.facebook.com":
                path = parsed.path.removeprefix("/v26.0/")
                if method == "GET" and path == APP_ID + "/subscriptions":
                    return FakeResponse({"data": [existing] if existing else []})
                if method == "GET" and path == PAGE_ID + "/subscribed_apps":
                    return FakeResponse({"data": [{"id": APP_ID, "subscribed_fields": FIELDS.split(",")} ]})
                if method == "POST" and path in {APP_ID + "/subscriptions", PAGE_ID + "/subscribed_apps"}:
                    return FakeResponse({"success": True})
            elif parsed.hostname == urllib.parse.urlsplit(callback).hostname:
                if parsed.path == "/readyz":
                    return FakeResponse({"status": "ready"}, status=ready_status)
                if parsed.path == "/webhook":
                    query = urllib.parse.parse_qs(parsed.query)
                    assert query["hub.mode"] == ["subscribe"]
                    assert query["hub.verify_token"] == ["fake-verify-token"]
                    challenge = query["hub.challenge"][0] if valid_challenge else "wrong-challenge"
                    return FakeResponse(challenge)
            raise AssertionError(f"Unexpected mocked operation: {method} {parsed.path}")

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        return calls

    return install


def test_existing_other_app_callback_is_preserved_without_post(registration, network):
    calls = network(existing={"object": "page", "callback_url": "https://existing.example/webhook", "active": True})
    with pytest.raises(SystemExit, match="different app callback"):
        registration.main()
    assert [call["method"] for call in calls] == ["GET"]
    assert not (registration.ROOT / ".local" / "meta-connected-url").exists()


@pytest.mark.parametrize("ready_status,valid_challenge", [(503, True), (200, False)])
def test_public_readiness_or_verification_failure_prevents_any_post(
    registration, network, ready_status, valid_challenge
):
    calls = network(ready_status=ready_status, valid_challenge=valid_challenge)
    with pytest.raises(SystemExit, match="readiness/verification failed"):
        registration.main()
    assert calls
    assert all(call["method"] == "GET" for call in calls)
    assert not (registration.ROOT / ".local" / "meta-connected-url").exists()


@pytest.mark.parametrize(
    "callback",
    [
        "http://test-onboarding.trycloudflare.com/webhook",
        "https://other.example/webhook",
        "https://nottrycloudflare.com/webhook",
        "https://test-onboarding.trycloudflare.com/other",
        "https://test-onboarding.trycloudflare.com/webhook?token=private",
        "https://test-onboarding.trycloudflare.com/webhook#fragment",
        "https://user:password@test-onboarding.trycloudflare.com/webhook",
        "https://test-onboarding.trycloudflare.com:443/webhook",
    ],
)
def test_invalid_callback_is_rejected_without_post(registration, network, callback):
    calls = network()
    (registration.ROOT / ".local" / "public-webhook-url").write_text(callback)
    with pytest.raises(SystemExit, match="Callback must be"):
        registration.main()
    assert [call["method"] for call in calls] == ["GET"]


@pytest.mark.parametrize('callback', [CALLBACK, 'https://example-codespace-8000.app.github.dev/webhook'])
def test_success_checks_public_endpoint_then_registers_exact_fields_in_order(
    registration, network, capsys, callback
):
    (registration.ROOT / '.local' / 'public-webhook-url').write_text(callback)
    calls = network(callback=callback)
    registration.main()
    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "POST", "POST"]
    app_call, page_call = [call for call in calls if call["method"] == "POST"]
    assert app_call["url"].endswith("/" + APP_ID + "/subscriptions")
    assert app_call["parameters"] == {
        "object": ["page"],
        "callback_url": [callback],
        "verify_token": ["fake-verify-token"],
        "fields": [FIELDS],
        "include_values": ["true"],
    }
    assert app_call["authorization"] == "Bearer " + APP_ID + "|fake-app-secret"
    assert page_call["url"].endswith("/" + PAGE_ID + "/subscribed_apps")
    assert page_call["parameters"] == {"subscribed_fields": [FIELDS]}
    assert page_call["authorization"] == "Bearer fake-page-token"
    record = registration.ROOT / ".local" / "meta-connected-url"
    assert record.read_text() == callback + "\n"
    assert record.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert "accepted the Page event subscription" in output
    for fake_secret in ("fake-app-secret", "fake-page-token", "fake-verify-token"):
        assert fake_secret not in output


def test_status_uses_only_graph_get_and_does_not_need_tunnel_file(
    registration, network, monkeypatch, capsys
):
    calls = network(existing={"object": "page", "callback_url": CALLBACK, "active": True})
    (registration.ROOT / ".local" / "public-webhook-url").unlink()
    monkeypatch.setattr(sys, "argv", ["connect-meta-webhook.py", "--status"])
    registration.main()
    assert [call["method"] for call in calls] == ["GET", "GET"]
    assert all(urllib.parse.urlsplit(call["url"]).hostname == "graph.facebook.com" for call in calls)
    assert json.loads(capsys.readouterr().out) == {
        "app_page_webhook_active": True,
        "callback_url": CALLBACK,
        "page_subscribed_fields": FIELDS.split(","),
    }
    assert not (registration.ROOT / ".local" / "meta-connected-url").exists()
