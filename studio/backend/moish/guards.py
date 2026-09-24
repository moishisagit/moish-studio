"""Studio has no working code path to a model (Invariant 3 as amended; plan.md §2.4a).

The Moish-owned llama-server is the only runtime. Every place Studio could start one of its
own — llama-server, the torch orchestrator, stable-diffusion, the RAG embedders, the
speech sidecars — raises here instead. The fork install also ships no runtime binaries and
no torch, so these guards are the second layer, not the only one.

Tools are forced off (``set_tool_policy(False)``: Moish executes tools, phase 2), and keyless
API access is refused, so nothing reaches Studio's API without a Studio session.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

MESSAGE = (
    "Local model runtimes are disabled in this build: every model call goes through the "
    "Moish gateway (Studio slice 1)."
)


class LocalRuntimeForbidden(RuntimeError):
    """Something tried to start a model runtime inside Studio."""


def _forbidden(*_a: Any, **_k: Any) -> Any:
    raise LocalRuntimeForbidden(MESSAGE)


#: (module, class, method) — each is an entry that loads weights or spawns a runtime.
GUARDED: tuple[tuple[str, str, str], ...] = (
    ("core.inference.llama_cpp", "LlamaCppBackend", "load_model"),
    ("core.inference.orchestrator", "InferenceOrchestrator", "load_model"),
    ("core.inference.sd_cpp_server", "SdCppServer", "start"),
    ("core.rag.embed_llama_server", "LlamaServerBackend", "_spawn"),
    ("core.rag.embeddings", "_SentenceTransformersBackend", "encode"),
    ("core.rag.embeddings", "_SentenceTransformersBackend", "warm"),
)
#: Modules whose every class ``start`` launches a speech sidecar or its download.
GUARDED_START_MODULES: tuple[str, ...] = (
    "core.inference.stt_sidecar",
    "core.inference.stt_ggml_sidecar",
    "core.inference.stt_mtmd_sidecar",
)


def guarded_entries() -> list[tuple[str, str, str]]:
    entries = list(GUARDED)
    for name in GUARDED_START_MODULES:
        module = importlib.import_module(name)
        for cls_name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == name and "start" in vars(cls):
                entries.append((name, cls_name, "start"))
    return entries


def forbid_local_runtime() -> list[str]:
    """Replace every runtime entry with a raising stub. Returns what was guarded."""
    done: list[str] = []
    for module_name, cls_name, method in guarded_entries():
        cls = getattr(importlib.import_module(module_name), cls_name)
        setattr(cls, method, _forbidden)
        done.append(f"{module_name}.{cls_name}.{method}")
    return done


def tools_off() -> None:
    from state import tool_policy

    tool_policy.set_tool_policy_default(False)
    tool_policy.set_tool_policy(False)


def keyless_off() -> None:
    from utils import keyless_api_access

    keyless_api_access.keyless_request_allowed = lambda *_a, **_k: False


def apply() -> list[str]:
    guarded = forbid_local_runtime()
    tools_off()
    keyless_off()
    return guarded
