"""Exercise the Docker-free receiver using private, temporary SQLite files."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from app import create_app, storage


PAGE_ID = '1177978082066315'
TEST_SECRET = 'synthetic-sqlite-integration-signing-key'


def make_app(path):
    return create_app({
        'TESTING': True,
        'DATABASE_ENGINE': 'sqlite',
        'SQLITE_PATH': str(path),
        'META_PAGE_ID': PAGE_ID,
        'META_APP_SECRET': TEST_SECRET,
        'META_VERIFY_TOKEN': 'synthetic-sqlite-verification-token',
    })


@pytest.fixture
def sqlite_app(tmp_path):
    app = make_app(tmp_path / 'private' / 'webhooks.sqlite3')
    with app.app_context():
        storage.init_db()
        storage.init_db()
    return app


def deliver(app, events, kind='messaging', timestamp=1700000000, signed=True):
    payload = {'object': 'page', 'entry': [{'id': PAGE_ID, 'time': timestamp, kind: events}]}
    raw = json.dumps(payload, ensure_ascii=False).encode()
    headers = {}
    if signed:
        headers['X-Hub-Signature-256'] = 'sha256=' + hmac.new(
            TEST_SECRET.encode(), raw, hashlib.sha256,
        ).hexdigest()
    return app.test_client().post('/webhook', data=raw, content_type='application/json', headers=headers)


def query(app, sql, parameters=()):
    with sqlite3.connect(app.config['SQLITE_PATH']) as connection:
        return connection.execute(sql, parameters).fetchall()


def test_readiness_needs_initialized_schema_and_private_database(tmp_path):
    path = tmp_path / 'private' / 'receiver.sqlite3'
    app = make_app(path)
    before = app.test_client().get('/readyz')
    assert before.status_code == 503
    assert before.get_json()['checks']['database'] is False
    assert not path.exists()
    with app.app_context():
        storage.init_db()
        storage.init_db()
    assert app.test_client().get('/readyz').status_code == 200
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_signed_messages_keep_unicode_attachments_echo_and_survive_restart(sqlite_app):
    attachments = [{'type': 'image', 'payload': {'url': 'https://example.test/stone.jpg'}}]
    event = {
        'sender': {'id': PAGE_ID}, 'recipient': {'id': 'synthetic-customer'},
        'timestamp': 1700000000123,
        'message': {'mid': 'synthetic-echo', 'text': 'Đá cảnh tự nhiên 🪨',
                    'attachments': attachments, 'is_echo': True},
    }
    response = deliver(sqlite_app, [event])
    assert response.status_code == 200
    assert response.get_json()['stored_events'] == 1
    row = query(sqlite_app, 'SELECT sender_id,recipient_id,timestamp_ms,body_text,attachments,is_echo FROM messages')[0]
    assert row[:4] == (PAGE_ID, 'synthetic-customer', 1700000000123, 'Đá cảnh tự nhiên 🪨')
    assert json.loads(row[4]) == attachments
    assert row[5] == 1
    restarted = make_app(Path(sqlite_app.config['SQLITE_PATH']))
    assert restarted.test_client().get('/readyz').status_code == 200
    assert query(restarted, 'SELECT COUNT(*) FROM messages') == [(1,)]


def test_retries_and_case_sensitive_message_ids(sqlite_app):
    event = {'timestamp': 1700000000000, 'message': {'mid': 'CaseSensitive.A', 'text': 'Giá đá?'}}
    assert deliver(sqlite_app, [event]).get_json()['stored_events'] == 1
    # Different JSON key order and envelope time still identify the same logical event.
    reordered = {'message': {'text': 'Giá đá?', 'mid': 'CaseSensitive.A'}, 'timestamp': 1700000000000}
    retry = deliver(sqlite_app, [reordered], timestamp=1700000005)
    assert retry.status_code == 200
    assert retry.get_json()['duplicate_events'] == 1
    event['timestamp'] += 1
    assert deliver(sqlite_app, [event]).status_code == 200
    assert query(sqlite_app, 'SELECT COUNT(*) FROM messages') == [(1,)]
    event['message']['mid'] = 'CaseSensitive.a'
    assert deliver(sqlite_app, [event]).status_code == 200
    assert query(sqlite_app, 'SELECT COUNT(*) FROM messages') == [(2,)]
    assert query(sqlite_app, 'SELECT COUNT(*) FROM webhook_events') == [(3,)]


def test_comment_edit_delete_preserves_metadata_and_rejects_older_updates(sqlite_app):
    value = {
        'item': 'comment', 'comment_id': 'synthetic-post_comment', 'post_id': 'synthetic-post',
        'created_time': 1700000000, 'from': {'id': 'synthetic-customer'},
        'verb': 'add', 'message': 'Giá bao nhiêu?',
    }
    event = {'field': 'feed', 'value': value}
    assert deliver(sqlite_app, [event], 'changes', 1700000010000).status_code == 200
    value.update(verb='edited', message='Báo giá và vận chuyển giúp tôi')
    assert deliver(sqlite_app, [event], 'changes', 1700000020).status_code == 200
    # Removal events may omit author, post, text and creation time.
    event['value'] = {'item': 'comment', 'comment_id': value['comment_id'], 'verb': 'remove'}
    assert deliver(sqlite_app, [event], 'changes', 1700000030).status_code == 200
    value.update(verb='edited', message='Bản sửa cũ đến muộn')
    event['value'] = value
    assert deliver(sqlite_app, [event], 'changes', 1700000015).status_code == 200
    row = query(sqlite_app, 'SELECT meta_post_id,author_id,body_text,is_deleted,verb,event_timestamp FROM comments')[0]
    assert row == ('synthetic-post', 'synthetic-customer', 'Báo giá và vận chuyển giúp tôi', 1, 'remove', 1700000030)


def test_database_failure_rolls_back_entire_delivery_and_allows_retry(sqlite_app):
    with sqlite3.connect(sqlite_app.config['SQLITE_PATH']) as connection:
        connection.execute('''
            CREATE TRIGGER synthetic_message_constraint BEFORE INSERT ON messages
            WHEN length(NEW.body_text) > 8
            BEGIN SELECT RAISE(ABORT, 'synthetic test constraint'); END
        ''')
    events = [
        {'message': {'mid': 'synthetic-first', 'text': 'test'}},
        {'message': {'mid': 'synthetic-second', 'text': 'Deliberately longer than the test constraint'}},
    ]
    response = deliver(sqlite_app, events)
    assert response.status_code == 503
    assert response.get_json()['error'] == 'storage_unavailable'
    assert query(sqlite_app, 'SELECT COUNT(*) FROM webhook_events') == [(0,)]
    assert query(sqlite_app, 'SELECT COUNT(*) FROM messages') == [(0,)]
    with sqlite3.connect(sqlite_app.config['SQLITE_PATH']) as connection:
        connection.execute('DROP TRIGGER synthetic_message_constraint')
    retried = deliver(sqlite_app, events)
    assert retried.status_code == 200
    assert retried.get_json()['stored_events'] == 2
    assert retried.get_json()['duplicate_events'] == 0


def test_unsigned_delivery_never_writes_to_sqlite(sqlite_app):
    response = deliver(sqlite_app, [{'message': {'mid': 'unsigned', 'text': 'untrusted'}}], signed=False)
    assert response.status_code == 403
    assert query(sqlite_app, 'SELECT COUNT(*) FROM webhook_events') == [(0,)]
    assert query(sqlite_app, 'SELECT COUNT(*) FROM messages') == [(0,)]


def test_parallel_retry_deliveries_store_once(sqlite_app):
    event = {'message': {'mid': 'parallel-synthetic-message', 'text': 'Thử nhiều worker'}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: deliver(sqlite_app, [event]), range(6)))
    assert all(response.status_code == 200 for response in responses)
    assert sum(response.get_json()['stored_events'] for response in responses) == 1
    assert sum(response.get_json()['duplicate_events'] for response in responses) == 5
    assert query(sqlite_app, 'SELECT COUNT(*) FROM webhook_events') == [(1,)]
    assert query(sqlite_app, 'SELECT COUNT(*) FROM messages') == [(1,)]
