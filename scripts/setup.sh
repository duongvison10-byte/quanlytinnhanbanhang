#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12 or newer is required"'
python3 -m venv .venv
PIP_CACHE_DIR="${PIP_CACHE_DIR:-/tmp/quanlytinnhanbanhang-pip-cache}" .venv/bin/python -m pip install --disable-pip-version-check --no-input --requirement requirements.txt
python3 scripts/generate-local-env.py
printf '%s\n' 'Đã cài phụ thuộc và chuẩn bị cấu hình cục bộ.'
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'Chưa có Docker Compose. Chạy bản thử không cần Docker: ./scripts/start.sh --sqlite'
fi
