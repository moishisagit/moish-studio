"""``register(app)`` — the one call ``main.py`` makes into the seam."""

from __future__ import annotations

import os
from typing import Any

from moish import config, guards, providers

_STATE: dict[str, Any] = {"guarded": []}


def register(app: Any) -> None:
    config.gateway_url()  # refuse to start with a non-loopback gateway
    providers.install_provider_store()
    _STATE["guarded"] = guards.apply()
    guards.refuse_downloads(app)

    @app.get("/api/moish/selfcheck")
    def moish_selfcheck() -> dict[str, Any]:
        """What this Studio can reach: nothing but the gateway (plan.md §2.4c)."""
        import sys

        children: list[int] = []
        try:
            import psutil

            children = [c.pid for c in psutil.Process(os.getpid()).children(recursive=True)]
        except Exception:  # noqa: BLE001 — psutil is optional here
            children = []
        from core.inference.providers import PROVIDER_REGISTRY

        return {
            "gateway": config.gateway_url(),
            "credential_present": config.read_token() is not None,
            "providers": sorted(PROVIDER_REGISTRY),
            "guarded_runtime_entries": list(_STATE["guarded"]),
            "child_processes": children,
            "torch_loaded": "torch" in sys.modules,
            "hf_offline": all(os.environ.get(v) == "1" for v in guards.OFFLINE_VARS),
            "downloads_refused": list(guards.DOWNLOAD_PATHS),
        }
