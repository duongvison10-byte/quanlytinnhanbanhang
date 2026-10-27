#!/usr/bin/env python3
"""Create private development configuration without revealing secret values."""

import argparse
import getpass
import os
from pathlib import Path
import re
import secrets
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-app-secret", action="store_true", help="Nhập Meta App Secret qua lời nhắc ẩn")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    destination = root / ".env"
    if destination.is_symlink():
        raise SystemExit("Refusing to replace a symlink .env file.")
    lines = destination.read_text().splitlines() if destination.exists() else []
    positions = {}
    for index, line in enumerate(lines):
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if match:
            positions[match.group(1)] = (index, match.group(2).strip())

    def put(key, value, replace=False):
        existing = positions.get(key)
        if existing and not replace:
            return
        new_line = key + "=" + value
        if existing:
            lines[existing[0]] = new_line
        else:
            positions[key] = (len(lines), value)
            lines.append(new_line)

    defaults = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": "3307",
        "MYSQL_DATABASE": "quanlytinnhanbanhang",
        "MYSQL_USER": "app",
        "MYSQL_DATA_DIR": os.environ.get("MYSQL_DATA_DIR", "./.local/mysql"),
        "META_PAGE_ID": "1177978082066315",
        "META_APP_SECRET": "",
    }
    for key, value in defaults.items():
        put(key, value)
    database_path = Path(positions['MYSQL_DATA_DIR'][1].strip("'\""))
    if not database_path.is_absolute():
        database_path = root / database_path
    try:
        existing_database = database_path.is_dir() and any(database_path.iterdir())
    except PermissionError:
        existing_database = True
    missing_database_password = any(
        not positions.get(key) or positions[key][1] in ('', "''", '""')
        for key in ('MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD')
    )
    if existing_database and missing_database_password:
        raise SystemExit('MySQL data already exists. Restore its original .env credentials before continuing.')
    for key in ("MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD", "META_VERIFY_TOKEN"):
        current = positions.get(key)
        if not current or current[1] in ("", "''", '""'):
            put(key, secrets.token_urlsafe(36), replace=True)
    if args.set_app_secret:
        if not sys.stdin.isatty():
            raise SystemExit("Use an interactive terminal to enter the App Secret securely.")
        value = getpass.getpass("Meta App Secret (ẩn): ").strip()
        if not value or any(char.isspace() for char in value):
            raise SystemExit("App Secret must be nonempty and contain no whitespace.")
        put("META_APP_SECRET", value, replace=True)

    temporary = root / (".env." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write("\n".join(lines) + "\n")
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    print("Đã chuẩn bị .env riêng tư; các giá trị bí mật không được hiển thị.")


if __name__ == "__main__":
    main()
