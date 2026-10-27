#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
./scripts/setup.sh
exec .venv/bin/python scripts/codespace-quickstart.py
