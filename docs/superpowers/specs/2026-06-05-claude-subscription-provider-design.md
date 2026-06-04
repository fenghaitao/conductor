# Claude Subscription Provider Design

**Date:** 2026-06-05
**Status:** Approved

## Summary

Add a `claude-subscription` provider that reuses `ClaudeProvider` but authenticates via the OAuth bearer token stored by the `claude` CLI (`claude login`) rather than `ANTHROPIC_API_KEY`. Users opt in by setting `provider: claude-subscription` in their workflow YAML. `ANTHROPIC_API_KEY` is ignored entirely on this path.

## Motivation

The existing `claude` provider requires an Anthropic API key (per-token billing). Users with a Claude Pro/Max subscription can authenticate via an OAuth bearer token instead. The Anthropic SDK already supports this via its `auth_token` parameter (`Authorization: Bearer <token>`); Conductor just needs to discover and wire up the token.

## Credential Discovery

A new shared helper `src/conductor/providers/claude_credentials.py` resolves the bearer token with this priority order:

1. Explicit `auth_token` kwarg (highest — for testing/overrides)
2. `ANTHROPIC_AUTH_TOKEN` environment variable
3. `~/.claude/.credentials.json` — parse and extract the OAuth token field

The helper returns the token string or raises `ProviderError` with the message:
> "No subscription credentials found — run 'claude login' or set ANTHROPIC_AUTH_TOKEN"

It never reads `ANTHROPIC_API_KEY`.

**Failure modes handled at discovery time:**
- File missing + env var unset → `ProviderError` with actionable message
- File present but malformed JSON → `ProviderError` including the file path and parse error

## Provider Changes

`ClaudeProvider.__init__` gains an `auth_token: str | None = None` parameter passed directly to `AsyncAnthropic(auth_token=...)`. When `auth_token` is set, `api_key` is forced to `None` so the SDK sends only the `Authorization: Bearer` header.

No new class is needed. `ClaudeProvider` already handles all stable capabilities; subscription auth is purely an initialization detail.

## Factory Changes

A new `"claude-subscription"` case in `create_provider`:
1. Calls the credential discovery helper to resolve the bearer token
2. Constructs `ClaudeProvider(api_key=None, auth_token=<token>, ...)` with the same kwargs as the `"claude"` case (model, temperature, max_tokens, timeout, mcp_servers, max_agent_iterations, max_session_seconds, default_reasoning_effort)

The `provider_type` `Literal` annotation gains `"claude-subscription"`. `ProviderFactory.create_provider` and `schema.py`'s provider name validation are updated to accept the new name.

**YAML usage:**
```yaml
runtime:
  provider: claude-subscription
```

## Capabilities

`claude-subscription` has identical `ProviderCapabilities` to `claude` — tier `stable`, full feature set (MCP tools, structured output, interrupts, reasoning effort, checkpoint resume: False). No carve-outs.

## Error Handling

| Failure | When | Response |
|---|---|---|
| Credentials not found | Factory construction | `ProviderError` with `"run 'claude login' or set ANTHROPIC_AUTH_TOKEN"` |
| Malformed credentials file | Factory construction | `ProviderError` with file path + parse error |
| Token expired (401) | First API call via `validate_connection()` | Existing non-retryable `ProviderError`; error message hints at re-running `claude login` |

`validate_connection()` is unchanged — `client.models.list()` fails fast with a 401 on expired tokens before any agents run.

## Schema & Validation

`conductor validate` accepts `"claude-subscription"` wherever `"claude"` is accepted. The provider name enum in `schema.py` gains the new value.

## Testing

**`tests/test_providers/test_claude_credentials.py`** — unit tests for discovery helper:
- Token found in `~/.claude/.credentials.json` → returns token string
- `ANTHROPIC_AUTH_TOKEN` set → returns it (file absent)
- Explicit `auth_token` kwarg → takes priority over both
- File missing + env var unset → `ProviderError` with actionable message
- File present but malformed JSON → `ProviderError` with file path

**`tests/test_providers/test_factory.py`** — factory tests:
- `"claude-subscription"` constructs `ClaudeProvider(api_key=None, auth_token=<token>)`
- `ANTHROPIC_API_KEY` in env is not forwarded
- Unknown provider name still raises `ProviderError`

**`tests/test_providers/test_claude.py`** — smoke test:
- `ClaudeProvider(api_key=None, auth_token="test-token")` initializes without error
- Mocked `AsyncAnthropic` receives `auth_token="test-token"` and `api_key=None`

No real-API integration test — credential discovery is fully mockable and the subscription token is not available in CI.

## Out of Scope

- Automatic token refresh (rely on user re-running `claude login`)
- Structured `runtime.provider` object support for `claude-subscription` (string shorthand only for now)
- Token caching across workflow runs
