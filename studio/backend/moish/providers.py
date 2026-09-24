"""The only provider Studio has: Moish (Invariant 8 — single authority).

``PROVIDER_REGISTRY`` in ``core/inference/providers.py`` is ``{"moish": MOISH_PROVIDER}``; the
cloud entries are deleted from the fork, not hidden. The provider STORE Studio reads
(``storage.providers_db``) is overridden so every account sees exactly one saved provider,
``moish``, pointed at the loopback gateway. Nothing is written to Studio's database and the
credential is never stored there: the seam client reads it at request time.
"""

from __future__ import annotations

from typing import Any

from moish import config

MOISH_PROVIDER: dict[str, Any] = {
    "display_name": "Moish",
    "base_url": config.DEFAULT_GATEWAY_URL,
    "default_models": [],
    # The gateway frames each completed turn as SSE (Moish plan.md O14).
    "supports_streaming": True,
    "supports_vision": False,
    # Tools are executed by Moish, never requested by Studio (phase 2).
    "supports_tool_calling": False,
    "studio_tools": False,
    "auth_header": "Authorization",
    "auth_prefix": "Bearer ",
    # A bearer key in Studio's terms (``Literal["api_key", "chatgpt_oauth"]``); the key itself is
    # the Moish client credential, read by the seam client at request time, never from the UI.
    "auth_kind": "api_key",
    "base_url_editable": False,
    "model_ids_editable": False,
    "model_list_mode": "remote",
    "notes": "The Moish gateway: Run-bound, keyed, loopback. The only model path in this build.",
    "body_omit": ("top_k", "min_p", "repetition_penalty", "presence_penalty"),
}

_TIMESTAMP = "2026-09-23T00:00:00+00:00"


def provider_row(models: list[str] | None = None) -> dict[str, Any]:
    """The synthetic saved-provider row every account sees."""
    listed = list(models or [])
    return {
        "id": config.PROVIDER_ID,
        "provider_type": config.PROVIDER_TYPE,
        "display_name": MOISH_PROVIDER["display_name"],
        "base_url": config.gateway_url(),
        "is_enabled": 1,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "models": listed,
        "available_models": listed,
        "max_output_tokens": None,
    }


def install_provider_store() -> None:
    """Make ``storage.providers_db`` show only the Moish provider, for every account."""
    from storage import providers_db

    if getattr(providers_db, "_moish_seam", False):
        return

    def get_provider(id: str) -> dict[str, Any] | None:
        return provider_row() if id == config.PROVIDER_ID else None

    def list_providers() -> list[dict[str, Any]]:
        return [provider_row()]

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise PermissionError("providers are fixed in this build: the only provider is Moish")

    providers_db.get_provider = get_provider
    providers_db.list_providers = list_providers
    providers_db.create_provider = refuse
    providers_db.update_provider = refuse
    providers_db.delete_provider = refuse
    providers_db._moish_seam = True
