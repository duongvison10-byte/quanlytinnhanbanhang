"""Minimal, signed Meta webhook receiver."""

import hashlib
import hmac
import os
import re
import sqlite3
from pathlib import Path

import click
import mysql.connector
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request

from . import storage


def _valid_id(value, limit=255):
    return value is None or (isinstance(value, (str, int)) and len(str(value)) <= limit)


def _valid_message(item):
    for field in ('sender', 'recipient'):
        value = item.get(field)
        if value is not None and (not isinstance(value, dict) or not _valid_id(value.get('id'), 64)):
            return False
    message = item.get('message')
    if message is None:
        return True
    return (
        isinstance(message, dict)
        and _valid_id(message.get('mid'))
        and (message.get('text') is None or isinstance(message['text'], str))
        and (message.get('attachments') is None or isinstance(message['attachments'], list))
    )


def _valid_change(item):
    value = item.get('value')
    if item.get('field') != 'feed' or not isinstance(value, dict) or value.get('item') != 'comment':
        return True
    author = value.get('from')
    return (
        _valid_id(value.get('comment_id'))
        and _valid_id(value.get('post_id'))
        and (author is None or (isinstance(author, dict) and _valid_id(author.get('id'), 64)))
        and (value.get('message') is None or isinstance(value['message'], str))
        and isinstance(value.get('verb', 'unknown'), str)
        and len(value.get('verb', 'unknown')) <= 32
    )


def create_app(test_config=None):
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)
    app = Flask(__name__)
    app.config.from_mapping(
        MAX_CONTENT_LENGTH=1024 * 1024,
        META_PAGE_ID=os.getenv('META_PAGE_ID', '1177978082066315'),
        META_APP_SECRET=os.getenv('META_APP_SECRET', ''),
        META_VERIFY_TOKEN=os.getenv('META_VERIFY_TOKEN', ''),
        META_PAGE_ACCESS_TOKEN=os.getenv('META_PAGE_ACCESS_TOKEN', ''),
        MYSQL_HOST=os.getenv('MYSQL_HOST', '127.0.0.1'),
        MYSQL_PORT=int(os.getenv('MYSQL_PORT', '3307')),
        MYSQL_DATABASE=os.getenv('MYSQL_DATABASE', 'quanlytinnhanbanhang'),
        MYSQL_USER=os.getenv('MYSQL_USER', 'app'),
        MYSQL_PASSWORD=os.getenv('MYSQL_PASSWORD', ''),
        DATABASE_ENGINE=os.getenv('DATABASE_ENGINE', 'mysql'),
        SQLITE_PATH=os.getenv('SQLITE_PATH', str(Path(__file__).resolve().parent.parent / '.local' / 'webhooks.sqlite3')),
    )
    if test_config:
        app.config.update(test_config)
    if app.config['DATABASE_ENGINE'] not in ('mysql', 'sqlite'):
        raise ValueError('DATABASE_ENGINE must be mysql or sqlite')

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    @app.get('/readyz')
    def ready():
        checks = {
            'database': storage.database_ready(),
            'app_secret': bool(app.config['META_APP_SECRET']),
            'verify_token': bool(app.config['META_VERIFY_TOKEN']),
        }
        ok = all(checks.values())
        return jsonify(status='ready' if ok else 'not_ready', checks=checks), 200 if ok else 503

    @app.get('/webhook')
    def verify_webhook():
        expected = app.config['META_VERIFY_TOKEN']
        if not expected:
            return jsonify(error='verification_not_configured'), 503
        supplied = request.args.get('hub.verify_token', '')
        challenge = request.args.get('hub.challenge', '')
        if request.args.get('hub.mode') != 'subscribe' or not hmac.compare_digest(supplied.encode(), expected.encode()):
            return jsonify(error='verification_failed'), 403
        if not challenge or len(challenge) > 1024:
            return jsonify(error='invalid_challenge'), 400
        return Response(challenge, mimetype='text/plain')

    @app.post('/webhook')
    def receive_webhook():
        secret = app.config['META_APP_SECRET']
        if not secret:
            return jsonify(error='signature_verification_not_configured'), 503
        signature = request.headers.get('X-Hub-Signature-256', '')
        raw = request.get_data(cache=True)
        expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not re.fullmatch(r'sha256=[0-9a-f]{64}', signature) or not hmac.compare_digest(signature, expected):
            return jsonify(error='invalid_signature'), 403
        if not request.is_json:
            return jsonify(error='json_required'), 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('object') != 'page':
            return jsonify(error='invalid_payload'), 400
        entries = payload.get('entry')
        if not isinstance(entries, list) or len(entries) > 100:
            return jsonify(error='invalid_entries'), 400
        for entry in entries:
            if not isinstance(entry, dict):
                return jsonify(error='invalid_entry'), 400
            if str(entry.get('id', '')) != app.config['META_PAGE_ID']:
                return jsonify(error='unexpected_page'), 403
            for field in ('messaging', 'changes'):
                items = entry.get(field, [])
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    return jsonify(error='invalid_events'), 400
                validator = _valid_message if field == 'messaging' else _valid_change
                if any(not validator(item) for item in items):
                    return jsonify(error='invalid_event_fields'), 400
        try:
            result = storage.persist_webhook(payload, app.config['META_PAGE_ID'])
        except (mysql.connector.Error, sqlite3.Error):
            app.logger.error('Webhook database write failed')
            return jsonify(error='storage_unavailable'), 503
        return jsonify(status='received', **result)

    @app.errorhandler(413)
    def oversized(_error):
        return jsonify(error='payload_too_large'), 413

    @app.cli.command('init-db')
    def init_db_command():
        """Create missing database tables without dropping existing data."""
        storage.init_db()
        click.echo('Database schema initialized.')

    @app.cli.command('send-message')
    @click.option('--recipient-id', required=True)
    @click.option('--text', required=True)
    def send_message_command(recipient_id, text):
        """Explicitly send one reply within Meta's allowed messaging window."""
        from .meta import MetaAPIError, send_message
        try:
            result = send_message(recipient_id, text)
        except (ValueError, MetaAPIError) as error:
            raise click.ClickException(str(error)) from None
        click.echo('Reply accepted by Meta. Message ID: ' + str(result.get('message_id', 'unknown')))

    return app
