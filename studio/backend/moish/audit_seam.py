"""Mutation audit for the Moish seam — prove the seam tests are load-bearing (Moish plan.md §7).

For each seam control, apply a source mutation that defeats it, run the seam tests, and
require them to FAIL. A mutation the tests survive means that control is guarded by prose.
Files are restored through bytes in a ``finally``; the script checks the tree afterwards.

Run from ``studio/backend`` with the fork's venv:  ``python -m moish.audit_seam``
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = ["moish/tests/test_seam.py"]


@dataclass
class Mutation:
    name: str
    target: str
    find: str
    replace: str


MUTATIONS = [
    Mutation(
        "a second provider is registered",
        "core/inference/providers.py",
        'PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {"moish": MOISH_PROVIDER}',
        'PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {"moish": MOISH_PROVIDER, "openai": {**MOISH_PROVIDER}}',
    ),
    Mutation(
        "the client accepts any provider type",
        "core/inference/external_provider.py",
        "        if provider_type not in PROVIDER_REGISTRY:",
        "        if False:",
    ),
    Mutation(
        "the caller's base URL reaches the moish client",
        "core/inference/external_provider.py",
        "            base_url = _moish_config.gateway_url()",
        "            base_url = base_url or _moish_config.gateway_url()",
    ),
    Mutation(
        "the gateway URL may leave loopback",
        "moish/config.py",
        '    if parts.scheme != "http" or not _loopback(parts.hostname):',
        "    if False:",
    ),
    Mutation(
        "the request carries presence_penalty",
        "moish/client.py",
        '        "stream": bool(stream),\n    }',
        '        "stream": bool(stream),\n        "presence_penalty": 0.0,\n    }',
    ),
    Mutation(
        "a tool turn is forwarded",
        "moish/client.py",
        '_ROLES = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant"}',
        '_ROLES = {"system": "system", "developer": "system", "user": "user", "assistant": "assistant", "tool": "user"}',
    ),
    Mutation(
        "a local runtime entry is left unguarded",
        "moish/guards.py",
        '    ("core.inference.llama_cpp", "LlamaCppBackend", "load_model"),\n',
        "",
    ),
    Mutation(
        "tools stay on",
        "moish/guards.py",
        "    tool_policy.set_tool_policy(False)",
        "    tool_policy.set_tool_policy(None)",
    ),
    Mutation(
        "the provider store accepts writes",
        "moish/providers.py",
        "    providers_db.create_provider = refuse\n",
        "",
    ),
    Mutation(
        "Studio binds any host",
        "run.py",
        "    if not _loopback:\n        raise SystemExit",
        "    if False:\n        raise SystemExit",
    ),
]


def _run_tests() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "-x", "-p", "no:cacheprovider"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _tree() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--", "."], cwd=BACKEND, capture_output=True, text=True
    ).stdout


def main() -> int:
    before = _tree()
    killed = survived = stale = 0
    for m in MUTATIONS:
        path = BACKEND / m.target
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(m.find) != 1:
            print(f"!! STALE     {m.name} ({m.target}: anchor found {text.count(m.find)}x)")
            stale += 1
            continue
        try:
            path.write_bytes(text.replace(m.find, m.replace).encode("utf-8"))
            passed = _run_tests()
        finally:
            path.write_bytes(original)
        if passed:
            print(f"!! SURVIVED  {m.name}")
            survived += 1
        else:
            print(f"ok killed    {m.name}")
            killed += 1
    restored = _tree() == before
    print("=" * 60)
    print(f"mutations: {len(MUTATIONS)}  killed: {killed}  survived: {survived}  stale: {stale}")
    print(f"working tree restored: {restored}")
    return 0 if survived == 0 and stale == 0 and restored else 1


if __name__ == "__main__":
    raise SystemExit(main())
