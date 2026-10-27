import copy
import re

from app.storage import prepare_events

from conftest import PAGE_ID


def test_message_event_has_stable_id_and_preserves_payload(delivery):
    event = prepare_events(delivery, PAGE_ID)[0]
    assert re.fullmatch(r"[0-9a-f]{64}", event["id"])
    assert event["page_id"] == PAGE_ID
    assert event["event_type"] == "message"
    assert event["payload"] == delivery["entry"][0]["messaging"][0]


def test_canonical_id_does_not_depend_on_json_key_order(delivery):
    reordered = copy.deepcopy(delivery)
    original = reordered["entry"][0]["messaging"][0]
    reordered["entry"][0]["messaging"][0] = dict(reversed(list(original.items())))
    assert prepare_events(delivery, PAGE_ID)[0]["id"] == prepare_events(reordered, PAGE_ID)[0]["id"]


def test_retry_in_different_batch_layout_retains_event_id(delivery):
    first_id = prepare_events(delivery, PAGE_ID)[0]["id"]
    rebatched = copy.deepcopy(delivery)
    another = copy.deepcopy(rebatched["entry"][0]["messaging"][0])
    another["message"]["mid"] = "different-message"
    rebatched["entry"][0]["time"] += 9999
    rebatched["entry"][0]["messaging"].insert(0, another)
    matching = next(
        event for event in prepare_events(rebatched, PAGE_ID)
        if event["payload"]["message"]["mid"] == "test-message-1"
    )
    assert matching["id"] == first_id


def test_event_identity_is_scoped_to_page(delivery):
    other = copy.deepcopy(delivery)
    other["entry"][0]["id"] = "another-page"
    assert prepare_events(delivery, PAGE_ID)[0]["id"] != prepare_events(other, "another-page")[0]["id"]


def test_feed_comment_is_distinguished_from_other_page_changes():
    comment = {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c1"}}
    post = {"field": "feed", "value": {"item": "post", "verb": "add", "post_id": "p1"}}
    payload = {"object": "page", "entry": [{"id": PAGE_ID, "changes": [comment, post]}]}
    events = prepare_events(payload, PAGE_ID)
    assert [event["event_type"] for event in events] == ["comment", "change"]
    assert events[0]["payload"] == comment
    assert events[1]["payload"] == post


def test_non_message_messaging_events_are_retained(delivery):
    event = {"sender": {"id": "test-customer"}, "delivery": {"mids": ["test-message-1"]}}
    delivery["entry"][0]["messaging"] = [event]
    prepared = prepare_events(delivery, PAGE_ID)
    assert len(prepared) == 1
    assert prepared[0]["event_type"] == "messaging"
    assert prepared[0]["payload"] == event
