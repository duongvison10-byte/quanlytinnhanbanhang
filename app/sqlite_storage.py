"""Private, transactional SQLite storage for a single development instance."""

import json
import os
from pathlib import Path
import sqlite3
import stat

from flask import current_app


def _database_path():
    return Path(current_app.config['SQLITE_PATH']).absolute()


def get_connection(*, readonly=False):
    """Open an existing database; ordinary requests never create a database file."""
    path = _database_path()
    if path.is_symlink():
        raise sqlite3.OperationalError('SQLite database must not be a symlink')
    mode = 'ro' if readonly else 'rw'
    connection = sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True, timeout=5)
    connection.execute('PRAGMA busy_timeout=5000')
    return connection


def init_db():
    path = _database_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise sqlite3.OperationalError('SQLite database must be a regular file')
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    connection = get_connection()
    try:
        # WAL allows readers while either of the two Gunicorn workers writes.
        connection.execute('PRAGMA journal_mode=WAL')
        connection.executescript(Path(__file__).with_name('schema_sqlite.sql').read_text())
        connection.commit()
    finally:
        connection.close()


def database_ready():
    try:
        connection = get_connection(readonly=True)
        try:
            for table in ('webhook_events', 'messages', 'comments'):
                connection.execute('SELECT id FROM ' + table + ' LIMIT 1').fetchall()
            return True
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return False


def persist_webhook(payload, page_id):
    # Keep normalization and canonical event IDs identical for both databases.
    from .storage import _integer, _string, prepare_events

    events = prepare_events(payload, page_id)
    connection = get_connection()
    result = {'stored_events': 0, 'duplicate_events': 0}
    try:
        connection.execute('BEGIN IMMEDIATE')
        for event in events:
            item = event['payload']
            cursor = connection.execute(
                'INSERT INTO webhook_events (id,page_id,event_type,payload) VALUES (?,?,?,?) '
                'ON CONFLICT(id) DO NOTHING',
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
                    connection.execute(
                        'INSERT INTO messages (page_id,meta_message_id,sender_id,recipient_id,timestamp_ms,body_text,attachments,is_echo,raw_event_id) '
                        'VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(page_id,meta_message_id) DO NOTHING',
                        (page_id, _string(message['mid']), _string(sender.get('id'), 64), _string(recipient.get('id'), 64),
                         _integer(item.get('timestamp')), message.get('text'), json.dumps(message.get('attachments') or []),
                         bool(message.get('is_echo')), event['id']),
                    )
            elif event['event_type'] == 'comment':
                value = item['value']
                if value.get('comment_id'):
                    author = value.get('from') or {}
                    connection.execute(
                        'INSERT INTO comments (page_id,meta_comment_id,meta_post_id,author_id,body_text,verb,is_deleted,event_timestamp,raw_event_id) '
                        'VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(page_id,meta_comment_id) DO UPDATE SET '
                        'meta_post_id=COALESCE(excluded.meta_post_id,comments.meta_post_id), '
                        'author_id=COALESCE(excluded.author_id,comments.author_id), '
                        'body_text=COALESCE(excluded.body_text,comments.body_text), '
                        'verb=excluded.verb, is_deleted=excluded.is_deleted, '
                        'event_timestamp=excluded.event_timestamp, raw_event_id=excluded.raw_event_id, '
                        "updated_at=strftime('%Y-%m-%d %H:%M:%f', 'now') "
                        'WHERE excluded.event_timestamp>=comments.event_timestamp',
                        (page_id, _string(value['comment_id']), _string(value.get('post_id')), _string(author.get('id'), 64),
                         value.get('message'), _string(value.get('verb', 'unknown'), 32), value.get('verb') == 'remove',
                         max(event['timestamp'], _integer(value.get('created_time'), 0)), event['id']),
                    )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return result
