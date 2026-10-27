#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

usage() {
  printf '%s\n' 'Usage: ./scripts/start.sh [--sqlite|--mysql] [start|status|stop]'
}

action=start
action_set=false
requested_engine=
for argument in "$@"; do
  case "$argument" in
    --sqlite|--mysql)
      next_engine="${argument#--}"
      if [[ -n "$requested_engine" && "$requested_engine" != "$next_engine" ]]; then
        usage >&2
        exit 2
      fi
      requested_engine="$next_engine"
      ;;
    start|status|stop)
      if [[ "$action_set" == true ]]; then
        usage >&2
        exit 2
      fi
      action="$argument"
      action_set=true
      ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

app_port="${APP_PORT:-8000}"
case "$app_port" in
  ''|*[!0-9]*) printf '%s\n' 'APP_PORT must be a numeric port.' >&2; exit 1 ;;
esac
mkdir -p .local
pid_file=.local/gunicorn.pid
engine_file=.local/storage-engine
running_engine_file=.local/gunicorn-storage-engine
saved_engine=mysql
if [[ -f "$engine_file" ]]; then
  IFS= read -r saved_engine < "$engine_file" || true
  case "$saved_engine" in
    mysql|sqlite) ;;
    *) printf '%s\n' 'Cấu hình .local/storage-engine không hợp lệ; cần mysql hoặc sqlite.' >&2; exit 1 ;;
  esac
fi
engine="${requested_engine:-$saved_engine}"
export DATABASE_ENGINE="$engine"

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
try:
    command = Path("/proc", sys.argv[1], "cmdline").read_bytes().replace(b"\0", b" ")
    directory_matches = Path("/proc", sys.argv[1], "cwd").resolve(strict=True) == Path.cwd().resolve()
except OSError:
    raise SystemExit(1) from None
raise SystemExit(0 if directory_matches and re.search(rb"gunicorn.*app:create_app", command) else 1)
PY
}

running_engine() {
  local value="$saved_engine"
  if [[ -f "$running_engine_file" ]]; then
    IFS= read -r value < "$running_engine_file" || true
  fi
  case "$value" in
    mysql|sqlite) printf '%s\n' "$value" ;;
    *) printf '%s\n' "$saved_engine" ;;
  esac
}

stop_server() {
  if server_running; then
    local server_pid
    IFS= read -r server_pid < "$pid_file"
    kill -TERM "$server_pid"
    for ((attempt = 0; attempt < 40; attempt++)); do
      if ! server_running; then
        rm -f "$pid_file" "$running_engine_file"
        return 0
      fi
      sleep 0.25
    done
    printf '%s\n' 'Flask chưa dừng; giữ PID để kiểm tra, chưa khởi động tiến trình mới.' >&2
    return 1
  fi
  rm -f "$pid_file" "$running_engine_file"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    printf '%s\n' 'Chưa có Docker Compose. Chạy bản thử ngay bằng ./scripts/start.sh --sqlite hoặc rebuild Codespace để áp dụng Docker feature.' >&2
    return 1
  fi
}

case "$action" in
  start)
    [[ -x .venv/bin/gunicorn ]] || { printf '%s\n' 'Run ./scripts/setup.sh first.' >&2; exit 1; }
    python3 scripts/generate-local-env.py
    if [[ "$engine" == mysql ]]; then
      require_docker
      docker compose --env-file .env up --detach --wait --wait-timeout 150 mysql
    fi
    .venv/bin/python -m flask --app app init-db
    if server_running; then
      if [[ "$(running_engine)" == "$engine" ]]; then
        printf '%s\n' "$engine" > "$engine_file"
        printf '%s\n' "Flask đã chạy với $engine; dùng status để kiểm tra."
        exit 0
      fi
      stop_server
    fi
    .venv/bin/python - "$app_port" <<'PY'
import socket
import sys
with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit("APP_PORT đang được dịch vụ khác sử dụng; chọn cổng khác hoặc kiểm tra tiến trình cũ.") from None
PY
    printf '%s\n' "$engine" > "$engine_file"
    nohup .venv/bin/gunicorn --bind "127.0.0.1:$app_port" --workers 2 --error-logfile .local/server.log 'app:create_app()' > .local/server.stdout.log 2>&1 &
    server_pid=$!
    printf '%s\n' "$server_pid" > "$pid_file"
    printf '%s\n' "$engine" > "$running_engine_file"
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
    printf '%s\n' "Storage engine: $engine"
    if server_running; then
      printf '%s\n' "Flask process: running ($(running_engine))"
    else
      printf '%s\n' 'Flask process: stopped'
    fi
    if [[ "$engine" == mysql ]]; then
      require_docker
      docker compose --env-file .env ps mysql
    fi
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
    stop_server
    if [[ "$engine" == mysql ]]; then
      require_docker
      docker compose --env-file .env stop mysql
    fi
    printf '%s\n' 'Đã dừng Flask và các dịch vụ của chế độ đã chọn; dữ liệu được giữ lại.'
    ;;
esac
