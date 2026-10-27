#!/usr/bin/env python3
"""Install the pinned official cloudflared binary after SHA-256 verification."""

import hashlib
import os
from pathlib import Path
import platform
import secrets
import sys
import urllib.error
import urllib.request


VERSION = "2026.10.4"
SHA256 = "ae5e8add7884b0531d66bbca4570d1de491ff6da51e4ebe7eb160cdf241d9e42"
URL = f"https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/cloudflared-linux-amd64"
MAX_BYTES = 64 * 1024 * 1024


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "amd64"):
        raise SystemExit("This pinned cloudflared artifact supports Linux amd64 only.")
    os.umask(0o077)
    root = Path(os.environ.get("CLOUD_ENV_DIR", "/workspace/.cloud-environment/quanlytinnhanbanhang"))
    directory = root / "bin"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / "cloudflared"
    if target.is_symlink():
        raise SystemExit("Refusing to replace a symlink cloudflared binary.")
    if target.exists() and file_digest(target) == SHA256:
        target.chmod(0o700)
        print(f"cloudflared {VERSION}: checksum verified; already installed.")
        return
    temporary = directory / (".cloudflared-" + secrets.token_hex(8) + ".download")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as destination:
            request = urllib.request.Request(URL, headers={"User-Agent": "quanlytinnhanbanhang-setup"})
            with urllib.request.urlopen(request, timeout=60) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise RuntimeError("Download exceeds expected artifact size limit.")
                    digest.update(chunk)
                    destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if digest.hexdigest() != SHA256:
            raise RuntimeError("SHA-256 verification failed; downloaded binary will not be used.")
        temporary.chmod(0o700)
        os.replace(temporary, target)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Official cloudflared download failed: HTTP {error.code}.") from None
    except urllib.error.URLError:
        raise SystemExit("Official cloudflared download failed; check connectivity and trusted CA configuration.") from None
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"cloudflared {VERSION}: installed after SHA-256 verification.")


if __name__ == "__main__":
    main()
