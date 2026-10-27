"""Transactional webhook persistence; logical message IDs prevent duplicates."""

import hashlib
import json
from pathlib import Path

import mysql.connector
from flask import current_app


def get_connection():
    config = current_app.config
    if config.get('DATABASE_ENGINE', 'mysql') == 'sqlite':
        from . import sqlite_storage
        return sqlite_storage.get_connection()
    return mysql.connector.connect(
        host=config['MYSQL_HOST'], port=config['MYSQL_PORT'],
        database=config['MYSQL_DATABASE'], user=config['MYSQL_USER'],
        password=config['MYSQL_PASSWORD'], connection_timeout=5,
        charset='utf8mb4', autocommit=False,
    )


def init_db():
    if current_app.config.get('DATABASE_ENGINE', 'mysql') == 'sqlite':
        from . import sqlite_storage
        return sqlite_storage.init_db()
    connection = get_connection()
    try:
        cursor = connection.cursor()
        for statement in Path(__file__).with_name('schema.sql').read_text().split(';'):
            if statement.strip():
                cursor.execute(statement)
        connection.commit()
        cursor.close()
    finally:
        connection.close()


def database_ready():
    if current_app.config.get('DATABASE_ENGINE', 'mysql') == 'sqlite':
        from . import sqlite_storage
        return sqlite_storage.database_ready()
    try:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute('SELECT id FROM webhook_events LIMIT 1')
            cursor.fetchall()
            cursor.close()
            return True
        finally:
            connection.close()
    except mysql.connector.Error:
        return False


def prepare_events(payload, page_id):
    events = []
    for entry in payload['entry']:
        for kind in ('messaging', 'changes'):
            for item in entry.get(kind, []):
                if kind == 'messaging':
                    event_type = 'message' if isinstance(item.get('message'), dict) else 'messaging'
                else:
                    value = item.get('value', {})
                    event_type = 'comment' if item.get('field') == 'feed' and isinstance(value, dict) and value.get('item') == 'comment' else 'change'
                canonical = json.dumps(item, sort_keys=True, separators=(',', ':'))
                event_id = hashlib.sha256((page_id + ':' + kind + ':' + canonical).encode()).hexdigest()
                timestamp = _integer(entry.get('time'), 0)
                if timestamp > 100_000_000_000:
                    timestamp //= 1000
                events.append({'id': event_id, 'page_id': page_id, 'event_type': event_type, 'payload': item, 'timestamp': timestamp})
    return events


def _string(value, limit=255):
    return str(value)[:limit] if value is not None else None


def _integer(value, default=None):
    try:
        result = int(value)
        return result if -(2**63) <= result < 2**63 else default
    except (ValueError, TypeError, OverflowError):
        return default


def persist_webhook(payload, page_id):
    if current_app.config.get('DATABASE_ENGINE', 'mysql') == 'sqlite':
        from . import sqlite_storage
        return sqlite_storage.persist_webhook(payload, page_id)
    events = prepare_events(payload, page_id)
    connection = get_connection()
    result = {'stored_events': 0, 'duplicate_events': 0}
    try:
        cursor = connection.cursor()
        for event in events:
            item = event['payload']
            cursor.execute(
                'INSERT IGNORE INTO webhook_events (id,page_id,event_type,payload) VALUES (%s,%s,%s,%s)',
                (event['id'], page_id, event['event_type'], json.dumps(item)),
            )
            if cursor.rowcount == 0:
                result['duplicate_events'] += 1
                continue
            result['stored_events'] += 1
            if event['event_type'] == 'message':
                message = item['message']
                if message.get('mid'):
                    sender = item.get('sender') or {}
                    recipient = item.get('recipient') or {}
                    cursor.execute(
                        'INSERT INTO messages (page_id,meta_message_id,sender_id,recipient_id,timestamp_ms,body_text,attachments,is_echo,raw_event_id) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE meta_message_id=messages.meta_message_id',
                        (page_id, _string(message['mid']), _string(sender.get('id'), 64), _string(recipient.get('id'), 64),
                         _integer(item.get('timestamp')), message.get('text'), json.dumps(message.get('attachments') or []), bool(message.get('is_echo')), event['id']),
                    )
            elif event['event_type'] == 'comment':
                value = item['value']
                if value.get('comment_id'):
                    author = value.get('from') or {}
                    cursor.execute(
                        'INSERT INTO comments (page_id,meta_comment_id,meta_post_id,author_id,body_text,verb,is_deleted,event_timestamp,raw_event_id) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming ON DUPLICATE KEY UPDATE '
                        'meta_post_id=IF(incoming.event_timestamp>=comments.event_timestamp,COALESCE(incoming.meta_post_id,comments.meta_post_id),comments.meta_post_id), '
                        'author_id=IF(incoming.event_timestamp>=comments.event_timestamp,COALESCE(incoming.author_id,comments.author_id),comments.author_id), '
                        'body_text=IF(incoming.event_timestamp>=comments.event_timestamp,COALESCE(incoming.body_text,comments.body_text),comments.body_text), '
                        'verb=IF(incoming.event_timestamp>=comments.event_timestamp,incoming.verb,comments.verb), '
                        'is_deleted=IF(incoming.event_timestamp>=comments.event_timestamp,incoming.is_deleted,comments.is_deleted), '
                        'raw_event_id=IF(incoming.event_timestamp>=comments.event_timestamp,incoming.raw_event_id,comments.raw_event_id), '
                        'event_timestamp=GREATEST(comments.event_timestamp,incoming.event_timestamp)',
                        (page_id, _string(value['comment_id']), _string(value.get('post_id')), _string(author.get('id'), 64),
                         value.get('message'), _string(value.get('verb', 'unknown'), 32), value.get('verb') == 'remove',
                         max(event['timestamp'], _integer(value.get('created_time'), 0)), event['id']),
                    )
        connection.commit()
        cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return result
