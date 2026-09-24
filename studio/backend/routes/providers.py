# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Provider routes — Moish seam build (Studio slice 1, Invariant 8).

The only provider is Moish (``moish/providers.py``). The same paths as upstream are served
so the frontend keeps working, but:

* the registry and the saved-provider list hold exactly the Moish gateway;
* creating, editing, re-keying or deleting a provider is refused (403) — providers are fixed;
* the model list comes from the gateway's ``/v1/models``;
* nothing here reaches the internet: the models.dev catalog fetch, the cloud pricing table
  and the ChatGPT/Codex account linking are gone from this build.

Upstream's version of this module is recorded in ``moish/UPSTREAM_DELTA.md``.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException

from auth.authentication import get_current_subject
from core.inference.key_exchange import get_public_key_fingerprint, get_public_key_pem
from core.inference.providers import get_provider_info, list_available_providers
from models.providers import (
    ModelCatalogResponse,
    ProviderModelCapabilityInfo,
    ProviderModelInfo,
    ProviderModelsRequest,
    ProviderRegistryEntry,
    ProviderResponse,
    ProviderTestRequest,
    ProviderTestResult,
)
from moish import client as moish_client
from moish import config as moish_config
from storage import providers_db

logger = structlog.get_logger(__name__)

router = APIRouter(dependencies = [Depends(get_current_subject)])

_FIXED = "Providers are fixed in this build: the only provider is Moish."


def _provider_response(row: dict) -> ProviderResponse:
    connected = moish_config.read_token() is not None
    return ProviderResponse(
        id = row["id"],
        provider_type = row["provider_type"],
        display_name = row["display_name"],
        base_url = row["base_url"],
        is_enabled = bool(row["is_enabled"]),
        has_api_key = connected,
        auth_kind = "api_key",
        auth_status = "connected" if connected else "disconnected",
        models = row.get("models") or [],
        available_models = row.get("available_models") or [],
        max_output_tokens = row.get("max_output_tokens"),
        created_at = row["created_at"],
        updated_at = row["updated_at"],
    )


def _require_moish(provider_type: Optional[str]) -> None:
    if get_provider_info(provider_type or "") is None:
        raise HTTPException(status_code = 400, detail = f"Unknown provider type: {provider_type}")


@router.get("/public-key")
async def get_public_key():
    """Unchanged: the frontend still encrypts any key it sends (it sends none for Moish)."""
    return {"public_key": get_public_key_pem(), "fingerprint": get_public_key_fingerprint()}


@router.get("/registry", response_model = list[ProviderRegistryEntry])
async def list_registry(include_hidden: bool = False):
    return list_available_providers(include_hidden = include_hidden)


@router.get("/pricing")
async def get_pricing_snapshot():
    """Local inference has no per-token price; the cloud pricing table is not in this build."""
    return {}


@router.get("/", response_model = list[ProviderResponse])
def list_provider_configs():
    return [_provider_response(row) for row in providers_db.list_providers()]


@router.post("/", status_code = 403)
async def create_provider_config():
    raise HTTPException(status_code = 403, detail = _FIXED)


@router.put("/{provider_id}")
async def update_provider_config(provider_id: str):
    raise HTTPException(status_code = 403, detail = _FIXED)


@router.put("/{provider_id}/api-key/migrate")
async def migrate_provider_api_key(provider_id: str):
    raise HTTPException(status_code = 403, detail = _FIXED)


@router.delete("/{provider_id}")
async def delete_provider_config(provider_id: str):
    raise HTTPException(status_code = 403, detail = _FIXED)


async def _gateway_models() -> list[dict]:
    try:
        return await moish_client.list_models()
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI as a clear 502
        logger.warning("moish.list_models_failed", error = str(exc))
        raise HTTPException(
            status_code = 502,
            detail = f"The Moish gateway did not list its models ({moish_config.gateway_url()}): {exc}",
        ) from None


@router.post("/test", response_model = ProviderTestResult)
async def test_provider(payload: ProviderTestRequest):
    _require_moish(payload.provider_type)
    if moish_config.read_token() is None:
        return ProviderTestResult(
            success = False,
            message = "No Studio credential yet: issue one from moish-platform (issue-client).",
        )
    try:
        models = await _gateway_models()
    except HTTPException as exc:
        return ProviderTestResult(success = False, message = str(exc.detail))
    return ProviderTestResult(
        success = True, message = "Connected to the Moish gateway.", models_count = len(models)
    )


@router.get("/model-catalog", response_model = ModelCatalogResponse)
async def get_model_catalog():
    """No remote catalog in this build (upstream fetched models.dev)."""
    return {"fetched_at": 0.0, "providers": {}}


@router.post("/model-capabilities", response_model = list[ProviderModelCapabilityInfo])
async def list_provider_model_capabilities(payload: ProviderModelsRequest):
    _require_moish(payload.provider_type)
    return [
        ProviderModelCapabilityInfo(id = m.get("id", ""), input_modalities = ["text"])
        for m in await _gateway_models()
    ]


@router.post("/models", response_model = list[ProviderModelInfo])
async def list_provider_models(payload: ProviderModelsRequest):
    _require_moish(payload.provider_type)
    return [
        ProviderModelInfo(
            id = m.get("id", ""),
            display_name = m.get("id", ""),
            context_length = None,
            owned_by = m.get("owned_by"),
        )
        for m in await _gateway_models()
    ]
