#!/usr/bin/env python3
"""Connect this app to its verified, temporary HTTPS callback without showing secrets."""

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent.parent


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true', help='Read existing subscriptions only')
    arguments = parser.parse_args()
    local = dotenv_values(ROOT / '.env')

    def setting(name, default=''):
        return os.environ.get(name) or local.get(name) or default

    app_id = setting('META_APP_ID', '29122218940802027')
    page_id = setting('META_PAGE_ID', '1177978082066315')
    app_secret = setting('META_APP_SECRET')
    page_token = setting('META_PAGE_ACCESS_TOKEN')
    verify_token = setting('META_VERIFY_TOKEN')
    if not all((app_secret, page_token, verify_token)) or not app_id.isdigit() or not page_id.isdigit():
        raise SystemExit('Required Meta configuration is missing; no secret values displayed.')
    app_token = app_id + '|' + app_secret

    def graph(path, token, parameters=None, method='GET'):
        data = urllib.parse.urlencode(parameters).encode() if parameters is not None else None
        request = urllib.request.Request(
            'https://graph.facebook.com/v26.0/' + path,
            data=data, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'},
        )
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get('error', {})
            except (ValueError, TypeError):
                detail = {}
            raise SystemExit(f'Meta API rejected {method} operation: HTTP {error.code}, code {detail.get("code", "unknown")}. Credentials withheld.') from None
        except Exception:
            raise SystemExit('Meta API request failed; request details withheld.') from None

    subscriptions = graph(app_id + '/subscriptions', app_token).get('data', [])
    existing = next((item for item in subscriptions if item.get('object') == 'page'), None)
    if arguments.status:
        page_apps = graph(page_id + '/subscribed_apps?fields=id,subscribed_fields', page_token).get('data', [])
        selected = next((item for item in page_apps if str(item.get('id')) == app_id), {})
        print(json.dumps({'app_page_webhook_active': bool(existing and existing.get('active')), 'callback_url': existing.get('callback_url') if existing else None, 'page_subscribed_fields': selected.get('subscribed_fields', [])}))
        return

    callback_path = ROOT / '.local' / 'public-webhook-url'
    try:
        callback = callback_path.read_text().strip()
    except OSError:
        raise SystemExit('Start the temporary tunnel before connecting Meta.') from None
    try:
        parsed = urllib.parse.urlsplit(callback)
        supported_host = parsed.hostname and parsed.hostname.endswith(('.trycloudflare.com', '.app.github.dev'))
        invalid_callback = parsed.scheme != 'https' or not supported_host or parsed.path != '/webhook' or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port
    except ValueError:
        invalid_callback = True
    if invalid_callback:
        raise SystemExit('Callback must be a temporary Cloudflare or GitHub Codespaces HTTPS /webhook URL.')
    record = ROOT / '.local' / 'meta-connected-url'
    previous = record.read_text().strip() if record.exists() else None
    if existing and existing.get('callback_url') not in (callback, previous):
        raise SystemExit('A different app callback already exists. It was preserved; review it before replacing it.')

    try:
        origin = parsed.scheme + '://' + parsed.netloc
        with urllib.request.urlopen(origin + '/readyz', timeout=20) as response:
            if response.status != 200:
                raise ValueError('not ready')
        challenge = 'meta-onboarding-verification'
        query = urllib.parse.urlencode({'hub.mode': 'subscribe', 'hub.verify_token': verify_token, 'hub.challenge': challenge})
        with urllib.request.urlopen(callback + '?' + query, timeout=20) as response:
            if response.read().decode() != challenge:
                raise ValueError('wrong challenge')
    except Exception:
        raise SystemExit('Public callback readiness/verification failed. Existing Meta configuration was preserved; request details withheld.') from None

    fields = 'messages,messaging_postbacks,feed'
    result = graph(app_id + '/subscriptions', app_token, {
        'object': 'page', 'callback_url': callback, 'verify_token': verify_token,
        'fields': fields, 'include_values': 'true',
    }, method='POST')
    if not result.get('success'):
        raise SystemExit('Meta did not confirm app webhook registration.')
    record.write_text(callback + '\n')
    result = graph(page_id + '/subscribed_apps', page_token, {'subscribed_fields': fields}, method='POST')
    if not result.get('success'):
        raise SystemExit('App callback was registered, but Meta did not confirm Page event subscription.')
    print('Meta verified the public callback and accepted the Page event subscription.')


if __name__ == '__main__':
    main()
