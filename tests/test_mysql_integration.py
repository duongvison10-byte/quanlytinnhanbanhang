"""Opt-in real MySQL tests in a fresh database, never customer data."""

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path

import mysql.connector
import pytest
from dotenv import dotenv_values

from app import create_app, storage


pytestmark = pytest.mark.skipif(os.getenv('RUN_MYSQL_TESTS') != '1', reason='Set RUN_MYSQL_TESTS=1 with local MySQL running')
PAGE_ID = '1177978082066315'
TEST_SECRET = 'synthetic-integration-signing-key'


@pytest.fixture
def mysql_app():
    values = dotenv_values(Path(__file__).resolve().parent.parent / '.env')
    options = dict(host=values['MYSQL_HOST'], port=int(values['MYSQL_PORT']), user='root', password=values['MYSQL_ROOT_PASSWORD'])
    admin = mysql.connector.connect(**options)
    database = 'webhook_test_' + uuid.uuid4().hex
    cursor = admin.cursor()
    cursor.execute(f'CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
    app = create_app({
        'TESTING': True, 'META_PAGE_ID': PAGE_ID, 'META_APP_SECRET': TEST_SECRET,
        'META_VERIFY_TOKEN': 'synthetic-verify-token', 'MYSQL_HOST': options['host'],
        'MYSQL_PORT': options['port'], 'MYSQL_USER': 'root', 'MYSQL_PASSWORD': options['password'],
        'MYSQL_DATABASE': database,
    })
    try:
        with app.app_context():
            storage.init_db()
            storage.init_db()
        yield app
    finally:
        cursor.execute(f'DROP DATABASE `{database}`')
        cursor.close()
        admin.close()


def post(app, event, kind='messaging', time=1700000000):
    payload = {'object': 'page', 'entry': [{'id': PAGE_ID, 'time': time, kind: [event]}]}
    raw = json.dumps(payload, ensure_ascii=False).encode()
    signature = 'sha256=' + hmac.new(TEST_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return app.test_client().post('/webhook', data=raw, content_type='application/json', headers={'X-Hub-Signature-256': signature})


def query(app, sql):
    with app.app_context():
        connection = storage.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor.fetchall()
        finally:
            connection.close()


def test_real_mysql_message_retries_and_case_sensitive_ids(mysql_app):
    event = {'sender': {'id': 'test-customer'}, 'recipient': {'id': PAGE_ID}, 'timestamp': 1700000000000,
             'message': {'mid': 'CaseSensitive.A', 'text': 'Đá cảnh thử nghiệm 🪨'}}
    first = post(mysql_app, event)
    assert first.status_code == 200
    assert first.get_json()['stored_events'] == 1
    repeated = post(mysql_app, event, time=1700000005)
    assert repeated.status_code == 200
    assert repeated.get_json()['duplicate_events'] == 1
    event['timestamp'] += 1
    assert post(mysql_app, event).status_code == 200
    assert query(mysql_app, 'SELECT COUNT(*) FROM messages')[0][0] == 1
    event['message']['mid'] = 'CaseSensitive.a'
    assert post(mysql_app, event).status_code == 200
    assert query(mysql_app, 'SELECT COUNT(*) FROM messages')[0][0] == 2
    assert query(mysql_app, 'SELECT body_text FROM messages LIMIT 1')[0][0] == 'Đá cảnh thử nghiệm 🪨'


def test_comment_edit_delete_and_out_of_order_delivery(mysql_app):
    value = {'item': 'comment', 'comment_id': 'post_comment', 'post_id': 'post', 'verb': 'add',
             'created_time': 1700000000, 'from': {'id': 'test-customer'}, 'message': 'Giá bao nhiêu?'}
    event = {'field': 'feed', 'value': value}
    assert post(mysql_app, event, 'changes', 1700000010).status_code == 200
    value.update(verb='edited', message='Xin báo giá và vận chuyển')
    assert post(mysql_app, event, 'changes', 1700000020).status_code == 200
    assert query(mysql_app, 'SELECT body_text FROM comments')[0][0] == 'Xin báo giá và vận chuyển'
    value.update(verb='remove')
    value.pop('message')
    assert post(mysql_app, event, 'changes', 1700000030).status_code == 200
    value.update(verb='edited', message='Bản cũ đến chậm')
    assert post(mysql_app, event, 'changes', 1700000015).status_code == 200
    row = query(mysql_app, 'SELECT body_text,is_deleted,event_timestamp FROM comments')[0]
    assert row == ('Xin báo giá và vận chuyển', 1, 1700000030)


def test_readiness_and_real_transaction_rollback(mysql_app):
    assert mysql_app.test_client().get('/readyz').status_code == 200
    # A real database constraint failure on event 2 must roll back event 1 too.
    with mysql_app.app_context():
        connection = storage.get_connection()
        cursor = connection.cursor()
        cursor.execute('ALTER TABLE messages ADD CONSTRAINT test_body_limit CHECK (CHAR_LENGTH(body_text) <= 8)')
        cursor.close()
        connection.close()
    valid = {'message': {'mid': 'must-not-remain', 'text': 'test'}}
    invalid = {'message': {'mid': 'bad', 'text': 'Longer than the database test constraint allows'}}
    payload = {'object': 'page', 'entry': [{'id': PAGE_ID, 'messaging': [valid, invalid]}]}
    with mysql_app.app_context(), pytest.raises(mysql.connector.Error):
        storage.persist_webhook(payload, PAGE_ID)
    assert query(mysql_app, 'SELECT COUNT(*) FROM webhook_events')[0][0] == 0
    assert query(mysql_app, 'SELECT COUNT(*) FROM messages')[0][0] == 0
