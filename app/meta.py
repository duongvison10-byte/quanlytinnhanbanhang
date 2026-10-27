"""An explicit send command; incoming webhooks never auto-reply."""

import json
import urllib.error
import urllib.request

from flask import current_app


class MetaAPIError(Exception):
    pass


def send_message(recipient_id, text):
    if not recipient_id.isdigit() or not 1 <= len(text) <= 2000:
        raise ValueError('Recipient must be a Page-scoped numeric ID; text must contain 1–2000 characters.')
    config = current_app.config
    token = config['META_PAGE_ACCESS_TOKEN']
    if not token:
        raise ValueError('META_PAGE_ACCESS_TOKEN is not configured.')
    page_id = config['META_PAGE_ID']
    if not page_id.isdigit():
        raise ValueError('META_PAGE_ID must be numeric.')
    request = urllib.request.Request(
        f'https://graph.facebook.com/v26.0/{page_id}/messages',
        data=json.dumps({'recipient': {'id': recipient_id}, 'messaging_type': 'RESPONSE', 'message': {'text': text}}).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            details = json.loads(error.read()).get('error', {})
        except (ValueError, TypeError):
            details = {}
        raise MetaAPIError(f'Meta rejected the reply (HTTP {error.code}, code {details.get("code", "unknown")}).') from None
    except urllib.error.URLError:
        raise MetaAPIError('Could not reach Meta.') from None
