#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

action="${1:-start}"
app_port="${APP_PORT:-8000}"
case "$app_port" in
  ''|*[!0-9]*) printf '%s\n' 'APP_PORT must be a numeric port.' >&2; exit 1 ;;
esac
mkdir -p .local
pid_file=.local/gunicorn.pid

server_running() {
  [[ -s "$pid_file" ]] || return 1
  local server_pid
  IFS= read -r server_pid < "$pid_file"
  [[ "$server_pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$server_pid" 2>/dev/null || return 1
  [[ -r "/proc/$server_pid/cmdline" ]] || return 1
  python3 - "$server_pid" <<'PY'
from pathlib import Path
import re
import sys
command = Path("/proc", sys.argv[1], "cmdline").read_bytes().replace(b"\0", b" ")
raise SystemExit(0 if re.search(rb"gunicorn.*app:create_app", command) else 1)
PY
}

case "$action" in
  start)
    [[ -x .venv/bin/gunicorn ]] || { printf '%s\n' 'Run ./scripts/setup.sh first.' >&2; exit 1; }
    python3 scripts/generate-local-env.py
    docker compose --env-file .env up --detach --wait --wait-timeout 150 mysql
    .venv/bin/python -m flask --app app init-db
    if server_running; then
      printf '%s\n' 'Flask đã chạy; dùng status để kiểm tra.'
      exit 0
    fi
    .venv/bin/python - "$app_port" <<'PY'
import socket
import sys
with socket.socket() as listener:
    try:
        listener.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit("APP_PORT đang được dịch vụ khác sử dụng; chọn cổng khác hoặc kiểm tra tiến trình cũ.") from None
PY
    nohup .venv/bin/gunicorn --bind "127.0.0.1:$app_port" --workers 2 --error-logfile .local/server.log 'app:create_app()' > .local/server.stdout.log 2>&1 &
    server_pid=$!
    printf '%s\n' "$server_pid" > "$pid_file"
    .venv/bin/python - "$app_port" <<'PY'
import sys
import time
import urllib.error
import urllib.request
port = int(sys.argv[1])
for _ in range(30):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            if response.status == 200:
                print("Flask đã khởi động và trả HTTP 200 ở kiểm tra nội bộ.")
                break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(0.5)
else:
    raise SystemExit("Flask chưa sẵn sàng; xem .local/server.log và .local/server.stdout.log.")
PY
    ;;
  status)
    if server_running; then
      printf '%s\n' 'Flask process: running'
    else
      printf '%s\n' 'Flask process: stopped'
    fi
    docker compose --env-file .env ps mysql
    if [[ -x .venv/bin/python ]]; then
      .venv/bin/python - "$app_port" <<'PY'
import sys
import urllib.error
import urllib.request
for path in ("healthz", "readyz"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(sys.argv[1])}/{path}", timeout=3) as response:
            print(path + ": HTTP " + str(response.status))
    except urllib.error.HTTPError as error:
        print(path + ": HTTP " + str(error.code))
    except (urllib.error.URLError, TimeoutError):
        print(path + ": unavailable")
PY
    fi
    ;;
  stop)
    if server_running; then
      IFS= read -r server_pid < "$pid_file"
      kill -TERM "$server_pid"
      rm -f "$pid_file"
    fi
    docker compose --env-file .env stop mysql
    printf '%s\n' 'Đã dừng các dịch vụ; dữ liệu MySQL được giữ lại.'
    ;;
  *) printf '%s\n' 'Usage: ./scripts/start.sh [start|status|stop]' >&2; exit 2 ;;
esac
