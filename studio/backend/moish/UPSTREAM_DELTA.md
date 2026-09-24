# UPSTREAM_DELTA — every edit this fork makes to upstream Unsloth Studio

Base: `unslothai/unsloth` @ `d3909e6f451c994f214f8e21470f3bf52699388d` (branch `moish/base`).
Branch: `moish/slice1`. Authority: Moish `plan.md` §4.2 (the seam), §7 (Invariant 8),
§1.3 decisions O14–O18. Everything Moish-specific lives in `studio/backend/moish/`; the
edits below are the thinnest calls into it, plus deletions. **Merge-conflict risk** is
marked for the next upstream sync (itself a governed, human-initiated network operation).

## Added (fork-owned, not upstream)

| Path | Purpose |
|---|---|
| `studio/backend/moish/` | the seam: `config`, `providers`, `client`, `guards`, `seam.register`, `/api/moish/selfcheck`, `tests/test_seam.py`, `audit_seam.py`, this file |

## Edited upstream files

| File | Edit | Why | Conflict risk |
|---|---|---|---|
| `studio/backend/main.py` | `moish.register(app)` before the first router; unmounted: `openai_codex_auth`, `research_runs`, `video` ×3, `mcp_servers`, `skills`, `data_recipe`, `llama`, `whisper`, `export`, `rag`, `hub_datasets`, `hub_token`, `youtube`, `training`, `training_history`; `/mcp` never mounted; release-notes route and Codex shutdown removed; `llama_cpp` version reported as `None` | single authority; no ungoverned network; no runtime in Studio | **high** |
| `studio/backend/core/inference/providers.py` | `PROVIDER_REGISTRY = {"moish": MOISH_PROVIDER}` — 432 lines of cloud/self-hosted entries deleted; one comment host literal neutralised | Invariant 8: cloud code absent | **high** |
| `studio/backend/core/inference/external_provider.py` | constructor refuses any type outside the registry; `moish` pins base URL + reads the credential file; `stream_chat_completion` routes `moish` to `moish.client.stream_moish` | the gateway is a whitelist (O14) | **high** |
| `studio/backend/routes/providers.py` | rewritten Moish-only: same paths; writes 403; models from the gateway; no models.dev fetch, no cloud pricing, no Codex | single authority, no network | **high** (whole-file) |
| `studio/backend/routes/inference.py` | the `openai_codex` branch (446 lines) and `_append_to_codex_instructions` deleted | cloud code absent | medium |
| `studio/backend/routes/__init__.py` | `openai_codex_auth_router` export removed | follows the deletion | low |
| `studio/backend/run.py` | refuses a non-loopback `--host` and `--secure`/`--cloudflare`; tunnel lifecycle removed; `_cloudflare_tunnel_should_start` always False; default port 8890 | loopback only (plan §1.2) | medium |
| `studio/backend/utils/remote_access_settings.py` | status/start/stop return "disabled" (same shape) | no tunnel | low |
| `unsloth_cli/__init__.py` | only `unsloth studio` is registered | plan §2.4a.5 | medium |
| `unsloth_cli/commands/studio.py` | `studio run` is no longer a command | bypass path §2.2 #12 | medium |

## Deleted upstream files

`studio/backend/cloudflare_tunnel.py`, `studio/backend/colab.py`,
`studio/backend/core/inference/openai_codex_client.py`, `…/openai_codex_auth.py`,
`…/openai_codex_tool_loop.py`, `studio/backend/routes/openai_codex_auth.py`,
`studio/backend/routes/llama.py`, `studio/backend/utils/llama_cpp_update.py`,
`studio/backend/utils/release_notes.py`, `unsloth_cli/commands/start.py`,
`unsloth_cli/commands/chat.py`, `unsloth_cli/commands/inference.py`,
`unsloth_cli/claude_subagent_mcp.py`, `unsloth_cli/codex_subagent_mcp.py`.

## Deliberately kept (decisions)

- `routes/provider_credentials.py` — a generic UI-session / credential guard used by settings
  and inference, not cloud code (O18).
- Residual cloud host literals in unreachable translation code and frontend files — pinned by
  `tests/cloud_literal_ratchet.json` so they can only shrink (O16). Tracked in Moish
  `docs/known-issues.md`.
- The frontend is unchanged in slice 1: with the registry `{moish}` and the store fixed, the
  UI offers only Moish (O17 note). Removing the dead provider UI is phase 2 work with `ui/`.

## Verify

```
cd studio/backend
python -m pytest moish/tests -p no:cacheprovider      # seam bypass tests
python -m moish.audit_seam                            # every control has a killing test
```
