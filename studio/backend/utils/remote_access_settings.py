# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Persisted policy and non-blocking runtime operations for Remote access."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from loggers import get_logger

logger = get_logger(__name__)

REMOTE_ACCESS_AUTO_START_KEY = "remote_access_auto_start"
DEFAULT_REMOTE_ACCESS_AUTO_START = False
# Longest a Stop waits for a live start worker to claim settings ownership.
_STOP_OWNERSHIP_WAIT = 5.0

_worker_lock = threading.Lock()
_start_worker: threading.Thread | None = None
_stop_worker: threading.Thread | None = None
_start_worker_admission: tuple[int, int] | None = None
_stop_worker_admission: tuple[int, int] | None = None
_stop_response_condition = threading.Condition()
_stop_responses_pending = 0
_stop_response_admission_open = True


class RemoteAccessStopResponseMiddleware:
    """Lease the connector for every Stop request from ASGI admission through response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/settings/remote-access/stop"
        ):
            await self.app(scope, receive, send)
            return

        release = acquire_remote_access_stop_response()
        if release is None:
            # Teardown has already linearized. Preserve downstream auth and
            # idempotent route behavior without admitting new drain work.
            await self.app(scope, receive, send)
            return

        async def _send(message):
            await send(message)
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                release()

        try:
            await self.app(scope, receive, _send)
        finally:
            release()


def acquire_remote_access_stop_response() -> Callable[[], None] | None:
    """Hold connector teardown until this HTTP response has been finalized."""
    global _stop_responses_pending
    with _stop_response_condition:
        if not _stop_response_admission_open:
            return None
        _stop_responses_pending += 1
        _stop_response_condition.notify_all()
    released = False

    def _release() -> None:
        nonlocal released
        global _stop_responses_pending
        with _stop_response_condition:
            if released:
                return
            released = True
            _stop_responses_pending -= 1
            _stop_response_condition.notify_all()

    return _release


def _open_remote_access_stop_response_admission() -> None:
    global _stop_response_admission_open
    with _stop_response_condition:
        _stop_response_admission_open = True
        _stop_response_condition.notify_all()


def _drain_and_close_remote_access_stop_responses() -> None:
    """Drain admitted responses, then close admission at the teardown boundary."""
    global _stop_response_admission_open
    deadline = time.monotonic() + 1.0
    quiet_deadline: float | None = None
    with _stop_response_condition:
        while True:
            now = time.monotonic()
            if now >= deadline:
                _stop_response_admission_open = False
                return
            if _stop_responses_pending:
                quiet_deadline = None
                _stop_response_condition.wait(min(0.05, deadline - now))
                continue
            if quiet_deadline is None:
                quiet_deadline = now + 0.05
            if now >= quiet_deadline:
                _stop_response_admission_open = False
                return
            _stop_response_condition.wait(min(quiet_deadline - now, deadline - now))


def _coerce_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def get_remote_access_auto_start() -> bool:
    """Read the preference, failing closed on missing, invalid, or unreadable data."""
    try:
        from storage.studio_db import get_app_setting
        stored = get_app_setting(REMOTE_ACCESS_AUTO_START_KEY, None)
    except Exception:
        return False
    parsed = _coerce_bool(stored)
    return parsed if parsed is not None else DEFAULT_REMOTE_ACCESS_AUTO_START


def set_remote_access_auto_start(enabled: bool) -> bool:
    if not isinstance(enabled, bool):
        raise ValueError("Remote access auto-start must be true or false.")
    from storage.studio_db import upsert_app_settings

    upsert_app_settings({REMOTE_ACCESS_AUTO_START_KEY: enabled})
    return enabled


def _admin_password_ready() -> bool:
    try:
        from auth.storage import DEFAULT_ADMIN_USERNAME, requires_password_change
        return not requires_password_change(DEFAULT_ADMIN_USERNAME)
    except Exception:
        return False


def configure_remote_access(
    app_state, *, port: int, intent: str, is_colab: bool, launch_managed: bool
) -> None:
    """Publish immutable launch policy used by every settings request."""
    app_state.remote_access_port = port
    app_state.remote_access_intent = intent
    app_state.remote_access_is_colab = bool(is_colab)
    app_state.remote_access_launch_managed = bool(launch_managed)
    app_state.remote_access_ready = False


def _worker_alive(worker: threading.Thread | None) -> bool:
    return worker is not None and worker.is_alive()


def _worker_is_current(
    worker: threading.Thread | None, admission: tuple[int, int] | None, current: tuple[int, int]
) -> bool:
    if not _worker_alive(worker) or admission is None or admission[0] != current[0]:
        return False
    return current[1] in {admission[1], admission[1] + 1}


def remote_access_status(app_state) -> dict:
    """Moish seam: remote access (the Cloudflare tunnel) does not exist in this build.
    Studio, the Moish gateway and the inference runtime bind loopback only (Moish plan.md §1.2)."""
    return {
        "state": "off",
        "url": None,
        "error": None,
        "auto_start": False,
        "available": False,
        "managed_by": None,
        "can_start": False,
        "can_stop": False,
        "block_reason": "explicitly_disabled",
        "password_pending": False,
        "streaming_supported": True,
    }


def start_remote_access(app_state) -> dict:
    """Moish seam: loopback only; there is no tunnel to start."""
    raise RuntimeError("explicitly_disabled")


def stop_remote_access(app_state) -> dict:
    """Moish seam: nothing to stop."""
    return remote_access_status(app_state)


def maybe_auto_start_remote_access(app_state) -> bool:
    """Schedule persisted auto-start when current launch policy permits it."""
    if not get_remote_access_auto_start():
        return False
    try:
        start_remote_access(app_state)
    except RuntimeError:
        return False
    return True
