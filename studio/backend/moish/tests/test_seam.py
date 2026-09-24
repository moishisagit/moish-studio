"""Fork-side bypass tests for the Moish seam (Studio slice 1; Moish plan.md §7).

Run from ``studio/backend`` with the fork's venv:
``python -m pytest moish/tests -p no:cacheprovider``

What they prove about THIS application (the honest limit — a same-user process can still
start its own runtime — is stated in Moish docs/invariants.md):

* the only provider is Moish, at a loopback gateway, and any other provider type is refused;
* the request sent to the gateway is exactly its whitelist — never tools;
* every local runtime entry raises; tools and keyless access are off;
* Studio refuses a non-loopback bind and has no tunnel;
* the cloud account-linking / tunnel / update files are absent, and the remaining cloud
  host literals can only shrink (a ratchet).
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parents[1]


def test_the_only_provider_is_moish() -> None:
    from core.inference.providers import PROVIDER_REGISTRY, list_available_providers

    assert set(PROVIDER_REGISTRY) == {"moish"}
    assert [p["provider_type"] for p in list_available_providers(include_hidden=True)] == ["moish"]


@pytest.mark.parametrize("provider_type", ["openai", "anthropic", "openai_codex", "custom", "ollama"])
def test_any_other_provider_type_is_refused(provider_type) -> None:
    from core.inference.external_provider import ExternalProviderClient

    with pytest.raises(ValueError, match="only provider is Moish"):
        ExternalProviderClient(provider_type, "http://127.0.0.1:9999/v1", "k")


def test_the_moish_client_is_pinned_to_the_loopback_gateway(monkeypatch, tmp_path) -> None:
    from core.inference.external_provider import ExternalProviderClient

    token = tmp_path / "studio.token"
    token.write_text("secret-from-file", encoding="utf-8")
    monkeypatch.setenv("MOISH_CLIENT_TOKEN_FILE", str(token))
    client = ExternalProviderClient("moish", "https://api.example.invalid/v1", "ignored")
    assert client.base_url == "http://127.0.0.1:8900/v1", "the caller cannot move the gateway"
    assert client.api_key == "secret-from-file", "the credential comes from the token file"


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:8900/v1", "https://gateway.example/v1", "http://0.0.0.0:8900/v1"]
)
def test_a_non_loopback_gateway_is_refused(monkeypatch, url) -> None:
    from moish import config

    monkeypatch.setenv("MOISH_GATEWAY_URL", url)
    with pytest.raises(config.SeamConfigError):
        config.gateway_url()


def test_the_gateway_request_is_exactly_the_whitelist() -> None:
    from moish.client import gateway_body

    body = gateway_body(
        [
            {"role": "developer", "content": "be brief"},
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ],
        "qwen2.5-coder-7b",
        temperature=0.7,
        top_p=0.95,
        max_tokens=64,
    )
    assert set(body) <= {"model", "messages", "temperature", "top_p", "max_tokens", "stop", "stream"}
    assert body["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]
    assert "tools" not in body and "presence_penalty" not in body


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:"}}]}],
        [],
    ],
    ids=["tool-role", "image-part", "empty"],
)
def test_what_the_gateway_cannot_take_is_refused_before_sending(messages) -> None:
    from moish.client import SeamRequestError, gateway_body

    with pytest.raises(SeamRequestError):
        gateway_body(messages, "m")


def test_without_a_credential_nothing_is_sent(monkeypatch, tmp_path) -> None:
    from moish import client

    monkeypatch.setenv("MOISH_CLIENT_TOKEN_FILE", str(tmp_path / "absent.token"))

    async def collect():
        return [line async for line in client.stream_moish([{"role": "user", "content": "hi"}], "m")]

    lines = asyncio.run(collect())
    assert len(lines) == 1 and "issue-client" in lines[0]


#: Pinned independently of guards.GUARDED, so dropping an entry there fails here.
REQUIRED_GUARDS = (
    ("core.inference.llama_cpp", "LlamaCppBackend", "load_model"),
    ("core.inference.orchestrator", "InferenceOrchestrator", "load_model"),
    ("core.inference.sd_cpp_server", "SdCppServer", "start"),
    ("core.rag.embed_llama_server", "LlamaServerBackend", "_spawn"),
    ("core.rag.embeddings", "_SentenceTransformersBackend", "encode"),
)


def test_every_local_runtime_entry_raises() -> None:
    import importlib

    from moish import guards

    guards.apply()
    entries = set(guards.guarded_entries())
    missing = [e for e in REQUIRED_GUARDS if e not in entries]
    assert missing == [], f"runtime entries no longer guarded: {missing}"
    for module_name, cls_name, method in sorted(entries | set(REQUIRED_GUARDS)):
        target = getattr(getattr(importlib.import_module(module_name), cls_name), method)
        with pytest.raises(guards.LocalRuntimeForbidden):
            target(object())
    from state import tool_policy

    assert tool_policy.get_tool_policy() is False
    from utils import keyless_api_access

    assert keyless_api_access.keyless_request_allowed(object()) is False


def test_the_provider_store_shows_only_moish_and_refuses_writes() -> None:
    from moish import providers
    from storage import providers_db

    providers.install_provider_store()
    assert [row["id"] for row in providers_db.list_providers()] == ["moish"]
    assert providers_db.get_provider("anything-else") is None
    with pytest.raises(PermissionError):
        providers_db.create_provider(
            id="x", provider_type="openai", display_name="x", base_url="https://x"
        )


def _provider_http(monkeypatch, list_models):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth.authentication import get_current_subject
    from moish import client, providers
    from routes import providers as provider_routes

    providers.install_provider_store()
    monkeypatch.setattr(client, "list_models", list_models)
    app = FastAPI()
    app.include_router(provider_routes.router, prefix="/api/providers")
    app.dependency_overrides[get_current_subject] = lambda: "test-subject"
    return TestClient(app)


def test_the_provider_routes_serve_what_the_frontend_syncs(monkeypatch) -> None:
    """The registry and saved-provider list pass Studio's own response models, and the saved
    Moish row lists the gateway's models — Studio's picker shows only a provider's saved models.

    Found live (2026-09-24): an ``auth_kind`` outside the response model's literal made
    ``/api/providers/registry`` answer 500, and the saved row carried ``models: []``, so the
    model picker showed no Moish model.
    """

    async def gateway_models(timeout: float = 15.0):
        return [{"id": "qwen2.5-coder-7b", "owned_by": "moish"}, {"id": "qwen3.8-27b-coder"}]

    with _provider_http(monkeypatch, gateway_models) as http:
        registry = http.get("/api/providers/registry", params={"include_hidden": "true"})
        saved = http.get("/api/providers/")
    assert registry.status_code == 200, registry.text
    assert [e["provider_type"] for e in registry.json()] == ["moish"]
    assert saved.status_code == 200, saved.text
    assert [(p["id"], p["is_enabled"]) for p in saved.json()] == [("moish", True)]
    assert saved.json()[0]["models"] == ["qwen2.5-coder-7b", "qwen3.8-27b-coder"]


def test_an_unreachable_gateway_still_lists_the_provider(monkeypatch) -> None:
    async def gateway_down(timeout: float = 15.0):
        raise OSError("connection refused")

    with _provider_http(monkeypatch, gateway_down) as http:
        saved = http.get("/api/providers/")
    assert saved.status_code == 200, saved.text
    assert [(p["id"], p["models"]) for p in saved.json()] == [("moish", [])]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::"])
def test_studio_refuses_a_non_loopback_bind(host) -> None:
    import run

    with pytest.raises(SystemExit, match="loopback only"):
        run.run_server(host=host, port=0, silent=True)


ABSENT = (
    "studio/backend/cloudflare_tunnel.py",
    "studio/backend/colab.py",
    "studio/backend/core/inference/openai_codex_client.py",
    "studio/backend/core/inference/openai_codex_auth.py",
    "studio/backend/core/inference/openai_codex_tool_loop.py",
    "studio/backend/routes/openai_codex_auth.py",
    "studio/backend/utils/llama_cpp_update.py",
    "studio/backend/utils/release_notes.py",
    "studio/backend/routes/llama.py",
    "unsloth_cli/commands/start.py",
    "unsloth_cli/commands/chat.py",
    "unsloth_cli/commands/inference.py",
    "unsloth_cli/claude_subagent_mcp.py",
    "unsloth_cli/codex_subagent_mcp.py",
)


def test_cloud_tunnel_and_update_code_is_absent() -> None:
    present = [p for p in ABSENT if (REPO / p).exists()]
    assert present == [], f"absent-by-design files are back: {present}"


HOSTS = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|openrouter\.ai|"
    r"api\.mistral\.ai|api\.groq\.com|api\.together\.xyz|api\.deepseek\.com|api\.x\.ai|"
    r"chatgpt\.com|auth\.openai\.com|trycloudflare\.com|api\.moonshot\.(ai|cn)|"
    r"dashscope\.aliyuncs\.com|api\.fireworks\.ai|api\.cerebras\.ai|api\.perplexity\.ai|"
    r"api\.cohere\.(ai|com)|api\.z\.ai|open\.bigmodel\.cn|api\.minimaxi?\.(chat|io)"
)


def _scan() -> dict[str, int]:
    found: dict[str, int] = {}
    files = subprocess.run(
        ["git", "ls-files", "studio/backend", "studio/frontend/src", "unsloth_cli"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for rel in files:
        if "/tests/" in rel or rel.startswith("studio/backend/moish/"):
            continue
        if not rel.endswith((".py", ".ts", ".tsx", ".json", ".js")):
            continue
        path = REPO / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        count = sum(1 for line in text.splitlines() if HOSTS.search(line))
        if count:
            found[rel] = count
    return found


def test_cloud_host_literals_only_shrink() -> None:
    baseline = json.loads(
        (Path(__file__).parent / "cloud_literal_ratchet.json").read_text(encoding="utf-8")
    )
    baseline.pop("_comment", None)
    current = _scan()
    grown = {f: n for f, n in current.items() if n > baseline.get(f, 0)}
    assert grown == {}, f"cloud host literals appeared or grew: {grown}"
    for must_be_clean in (
        "studio/backend/core/inference/providers.py",
        "studio/backend/routes/providers.py",
        "studio/backend/main.py",
        "studio/backend/run.py",
    ):
        assert must_be_clean not in current, f"{must_be_clean} names a cloud host"
