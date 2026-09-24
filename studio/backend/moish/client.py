"""The request the Moish gateway accepts — and nothing else.

Studio's OpenAI-compatible path sends whatever the UI's capability map allows (presence
penalty, top_k, tools, response_format, reasoning switches...). The gateway is a whitelist and
refuses anything outside it (422), so the ``moish`` provider does not go through that path:
``stream_moish`` builds exactly the gateway contract (Moish ``schemas/gateway_chat_request``)
and relays the gateway's SSE lines unchanged.

* messages: roles ``system`` / ``user`` / ``assistant`` only; ``developer`` maps to
  ``system``; multi-part content is reduced to its text. A non-text part (an image) is refused
  here with a clear message — slice 1 has no vision path.
* sampling: ``temperature``, ``top_p``, ``max_tokens``, ``stop``. Nothing else.
* no tools, ever: Moish executes tools (phase 2); Studio never asks.
* the credential comes from ``config.read_token()`` at request time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from moish import config

_ROLES = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant"}


class SeamRequestError(ValueError):
    """The conversation cannot be expressed in the gateway contract."""


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
            else:
                kind = part.get("type") if isinstance(part, dict) else type(part).__name__
                raise SeamRequestError(
                    f"this build sends text only to Moish; a {kind!r} part cannot be sent"
                )
        return "\n".join(p for p in parts if p)
    raise SeamRequestError(f"unsupported message content of type {type(content).__name__}")


def gateway_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages or []:
        role = _ROLES.get(str(m.get("role", "")))
        if role is None:
            # tool / function turns cannot occur: Studio tools are off in this build
            raise SeamRequestError(f"message role {m.get('role')!r} is not sent to Moish")
        out.append({"role": role, "content": _text(m.get("content"))})
    if not out:
        raise SeamRequestError("a conversation needs at least one message")
    return out


def gateway_body(
    messages: list[dict[str, Any]],
    model: str,
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stop: Any = None,
    stream: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": gateway_messages(messages),
        "stream": bool(stream),
    }
    if temperature is not None:
        body["temperature"] = max(0.0, min(2.0, float(temperature)))
    if top_p is not None and float(top_p) > 0:
        body["top_p"] = min(1.0, float(top_p))
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
    if stop:
        body["stop"] = stop if isinstance(stop, str) else list(stop)[:4]
    return body


def auth_headers() -> dict[str, str]:
    token = config.read_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def stream_moish(
    messages: list[dict[str, Any]],
    model: str,
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stream: bool = True,
    timeout: float = 600.0,
) -> AsyncGenerator[str, None]:
    """Yield the gateway's OpenAI-format SSE lines (``data: ...``), as Studio expects."""
    from core.inference.external_provider import _error_sse_line

    try:
        body = gateway_body(
            messages,
            model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=stream,
        )
    except SeamRequestError as exc:
        yield _error_sse_line(400, str(exc), config.PROVIDER_TYPE, None)
        return
    if config.read_token() is None:
        yield _error_sse_line(
            401,
            "Moish has not issued a Studio credential yet: run `uv run python -m control_plane "
            "issue-client --name studio --scope inference:interactive` in moish-platform.",
            config.PROVIDER_TYPE,
            None,
        )
        return
    url = f"{config.gateway_url()}/chat/completions"
    limits = httpx.Timeout(timeout, connect=10.0, read=timeout)
    try:
        async with httpx.AsyncClient(timeout=limits) as client:
            async with client.stream("POST", url, json=body, headers=auth_headers()) as response:
                if response.status_code != 200:
                    text = (await response.aread()).decode("utf-8", errors="replace")
                    yield _error_sse_line(response.status_code, text, config.PROVIDER_TYPE, None)
                    return
                if not response.headers.get("content-type", "").startswith("text/event-stream"):
                    # a non-streamed answer: re-frame it so Studio's stream consumer can read it
                    data = json.loads(await response.aread())
                    content = data["choices"][0]["message"]["content"]
                    chunk = {
                        "id": data.get("id", "chatcmpl-moish"),
                        "object": "chat.completion.chunk",
                        "model": data.get("model", model),
                        "choices": [
                            {"index": 0, "delta": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}
                        ],
                    }
                    yield f"data: {json.dumps(chunk)}"
                    yield "data: [DONE]"
                    return
                async for line in response.aiter_lines():
                    if line.strip():
                        yield line
    except httpx.HTTPError as exc:
        yield _error_sse_line(
            503, f"the Moish gateway is unreachable at {url}: {exc}", config.PROVIDER_TYPE, None
        )


async def list_models(timeout: float = 15.0) -> list[dict[str, Any]]:
    """The gateway's model list (``GET /v1/models``), in the shape Studio's picker expects."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{config.gateway_url()}/models", headers=auth_headers())
        response.raise_for_status()
        return list(response.json().get("data", []))
