---
name: claude-subscription-oauth-requirements
description: Conductor claude-subscription provider — OAuth token requirements and the misleading 429 gotcha
metadata:
  type: project
---

The `claude-subscription` provider in Conductor authenticates with the OAuth bearer
token from `claude login` (stored at `~/.claude/.credentials.json` under
`claudeAiOauth.accessToken` — NOT a flat `oauth_token` field).

**Critical gotcha:** A subscription request that is missing either OAuth requirement
fails with a *misleading* `429 rate_limit_error` whose body is just
`{'error': {'type': 'rate_limit_error', 'message': 'Error'}}` — it is NOT a real
rate limit. Two requirements (implemented in `src/conductor/providers/claude.py`):

1. Client must send header `anthropic-beta: oauth-2025-04-20` (set via
   `AsyncAnthropic(default_headers=...)` in `_initialize_client` when `auth_token` set).
2. The `system` prompt must be sent as an **array** whose first block is EXACTLY
   `"You are Claude Code, Anthropic's official CLI for Claude."`. A concatenated
   single string fails; a multi-block array `[{type:text,text:PREFIX}, {...agent system}]`
   works. Handled by `_wrap_system_for_subscription()`.

Also: a non-existent model name (e.g. `claude-sonnet-4-5` — the real one is
`claude-sonnet-4-6`) produces the SAME misleading 429, not a 404. When debugging a
429 here, first check the model exists via `client.models.list()`, then check the
two OAuth requirements. **Why:** these symptoms look like throttling and send you
down the wrong path (retry/backoff tuning). **How to apply:** when a subscription
429 appears, do NOT add retry/backoff — verify model name + OAuth header + system
identity block instead. See [[claude-subscription-provider-design]].
