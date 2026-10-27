#!/usr/bin/env python3
"""Start the SQLite trial and register its public Codespaces callback."""

import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent.parent


def run(*arguments):
    subprocess.run(arguments, cwd=ROOT, check=True)


def main():
    os.umask(0o077)
    name = os.environ.get('CODESPACE_NAME', '')
    domain = os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', name) or len(name) > 58 or domain != 'app.github.dev':
        raise SystemExit('Chạy lệnh này trong terminal GitHub Codespaces; cần CODESPACE_NAME và miền chuyển tiếp app.github.dev hợp lệ.')

    local = dotenv_values(ROOT / '.env')
    # An empty process variable must not hide a configured local App Secret.
    if not os.environ.get('META_APP_SECRET'):
        os.environ.pop('META_APP_SECRET', None)
    app_secret = os.environ.get('META_APP_SECRET') or local.get('META_APP_SECRET') or ''
    if not app_secret:
        if not sys.stdin.isatty():
            raise SystemExit('Mở terminal tương tác trong Codespace để nhập App Secret qua lời nhắc ẩn; không gửi bí mật vào chat.')
        print('Lấy App Secret tại Meta Developers → Cài đặt ứng dụng → Thông tin cơ bản; dán vào lời nhắc ẩn bên dưới, không gửi vào chat.', flush=True)
        run(sys.executable, 'scripts/generate-local-env.py', '--set-app-secret')

    run('./scripts/start.sh', '--sqlite', 'stop')
    run('./scripts/start.sh', '--sqlite', 'start')
    run('./scripts/start.sh', 'status')

    callback = f'https://{name}-8000.{domain}/webhook'
    directory = ROOT / '.local'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = directory / ('.public-webhook-url-' + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(callback + '\n')
        os.replace(temporary, directory / 'public-webhook-url')
    finally:
        temporary.unlink(missing_ok=True)

    try:
        run(sys.executable, 'scripts/connect-meta-webhook.py', '--app-only')
    except subprocess.CalledProcessError as error:
        print('Ứng dụng đã khởi động nhưng callback chưa được đăng ký. Xem thông báo lỗi đã ẩn thông tin bí mật ở trên.', file=sys.stderr)
        raise SystemExit(error.returncode or 1) from None
    print('Meta đã xác minh và lưu callback ứng dụng: ' + callback)
    print('Còn bước đăng ký sự kiện cho fanpage; lệnh này chưa thực hiện bước đó.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode or 1) from None
