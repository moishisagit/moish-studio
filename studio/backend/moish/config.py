"""Where Moish is, and how Studio proves who it is to it.

* The gateway URL is **loopback only**. ``MOISH_GATEWAY_URL`` may move the port, never the host.
* The Studio client credential is issued by the human (``python -m control_plane issue-client
  --name studio --scope inference:interactive``) and written to the Moish platform's
  ``var/clients/studio.token``. It is read here, at request time, and never stored in
  Studio's databases. ``MOISH_CLIENT_TOKEN_FILE`` overrides the path.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

PROVIDER_ID = "moish"
PROVIDER_TYPE = "moish"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:8900/v1"
#: C:\dev\moish\moish-studio\studio\backend\moish\config.py -> C:\dev\moish
_WORKSPACE = Path(__file__).resolve().parents[4]
DEFAULT_TOKEN_FILE = _WORKSPACE / "moish-platform" / "var" / "clients" / "studio.token"


class SeamConfigError(ValueError):
    """The seam is configured to leave the machine or is otherwise unusable."""


def _loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def gateway_url() -> str:
    url = (os.environ.get("MOISH_GATEWAY_URL") or DEFAULT_GATEWAY_URL).strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "http" or not _loopback(parts.hostname):
        raise SeamConfigError(f"the Moish gateway must be a loopback http URL, not {url!r}")
    return url


def token_file() -> Path:
    return Path(os.environ.get("MOISH_CLIENT_TOKEN_FILE") or DEFAULT_TOKEN_FILE)


def read_token() -> str | None:
    """The Studio client credential, or None when it has not been issued yet."""
    try:
        token = token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None
