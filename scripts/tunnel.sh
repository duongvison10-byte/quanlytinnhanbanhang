#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

action="${1:-start}"
cloud_env_dir="${CLOUD_ENV_DIR:-/workspace/.cloud-environment/quanlytinnhanbanhang}"
cloudflared_binary="$cloud_env_dir/bin/cloudflared"
pid_file=.local/cloudflared.pid
log_file=.local/cloudflared.log
url_file=.local/public-webhook-url
mkdir -p .local

tunnel_running() {
  python3 - "$pid_file" "$cloudflared_binary" <<'PY'
import os
from pathlib import Path
import sys
try:
    pid = int(Path(sys.argv[1]).read_text().strip())
    if pid <= 1:
        raise ValueError("invalid pid")
    os.kill(pid, 0)
    executable = Path(os.readlink(f"/proc/{pid}/exe"))
    arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    expected = Path(sys.argv[2]).resolve()
    valid = executable == expected and b"tunnel" in arguments and b"http://127.0.0.1:8000" in arguments
except (OSError, ValueError):
    valid = False
raise SystemExit(0 if valid else 1)
PY
}

stop_owned_tunnel() {
  if tunnel_running; then
    local tunnel_pid
    IFS= read -r tunnel_pid < "$pid_file"
    kill -TERM "$tunnel_pid"
    for _ in {1..20}; do
      if ! tunnel_running; then break; fi
      sleep 0.25
    done
    if tunnel_running; then kill -KILL "$tunnel_pid"; fi
  fi
  rm -f "$pid_file" "$url_file"
}

case "$action" in
  start)
    if tunnel_running; then
      printf '%s\n' 'Tunnel process is already running.'
      if [[ -s "$url_file" ]]; then cat "$url_file"; fi
      exit 0
    fi
    python3 - <<'PY'
import urllib.error
import urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open("http://127.0.0.1:8000/readyz", timeout=5) as response:
        if response.status != 200:
            raise SystemExit("Backend readiness check did not return HTTP 200.")
except urllib.error.HTTPError as error:
    raise SystemExit(f"Backend is not ready (HTTP {error.code}); configure App Secret and database first.") from None
except (urllib.error.URLError, TimeoutError):
    raise SystemExit("Backend is unavailable; start it before opening a tunnel.") from None
PY
    python3 scripts/install-cloudflared.py
    : > "$log_file"
    rm -f "$url_file"
    nohup "$cloudflared_binary" tunnel --no-autoupdate --protocol http2 --loglevel info --url http://127.0.0.1:8000 > "$log_file" 2>&1 &
    tunnel_pid=$!
    printf '%s\n' "$tunnel_pid" > "$pid_file"
    if ! python3 - "$tunnel_pid" "$log_file" "$url_file" <<'PY'
import os
from pathlib import Path
import re
import sys
import time
pid = int(sys.argv[1])
log = Path(sys.argv[2])
destination = Path(sys.argv[3])
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        raise SystemExit("cloudflared stopped before connecting; inspect .local/cloudflared.log.") from None
    text = log.read_text(errors="replace") if log.exists() else ""
    match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com\b", text)
    if match and "Registered tunnel connection" in text:
        callback = match.group(0) + "/webhook"
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(callback + "\n")
        print("Temporary public webhook URL: " + callback)
        print("Cloudflare registered the tunnel connection. Public HTTP validation is still required.")
        break
    time.sleep(0.5)
else:
    raise SystemExit("Tunnel did not connect within 60 seconds; inspect .local/cloudflared.log. Outbound TCP port 7844 is required.")
PY
    then
      stop_owned_tunnel
      exit 1
    fi
    ;;
  status)
    if tunnel_running; then
      printf '%s\n' 'Tunnel process: running'
      if [[ -s "$url_file" ]]; then cat "$url_file"; fi
      printf '%s\n' 'The saved URL records initial registration; validate public HTTP before using it.'
    else
      printf '%s\n' 'Tunnel process: stopped'
    fi
    ;;
  stop)
    stop_owned_tunnel
    printf '%s\n' 'Owned temporary tunnel stopped; its URL is no longer valid.'
    ;;
  *) printf '%s\n' 'Usage: ./scripts/tunnel.sh [start|status|stop]' >&2; exit 2 ;;
esac
