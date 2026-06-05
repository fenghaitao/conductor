# Claude Subscription Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `claude-subscription` provider that reuses `ClaudeProvider` but authenticates via OAuth bearer token from `claude login` instead of `ANTHROPIC_API_KEY`.

**Architecture:** A new shared credential-discovery module (`claude_credentials.py`) resolves the bearer token from explicit kwarg, `ANTHROPIC_AUTH_TOKEN` env var, or `~/.claude/.credentials.json`. `ClaudeProvider.__init__` gains an `auth_token` parameter; when set, `api_key` is forced to `None` so the SDK sends `Authorization: Bearer`. The factory (`create_provider`) gains a `"claude-subscription"` case that calls discovery and constructs a `ClaudeProvider` with the resolved token. Schema enumerations accept `"claude-subscription"` as a valid provider name.

**Tech Stack:** Python 3.12+, Pydantic v2, anthropic SDK, pytest with unittest.mock

**Spec:** `docs/superpowers/specs/2026-06-05-claude-subscription-provider-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `src/conductor/providers/claude_credentials.py` (create) | Resolve bearer token from kwarg / env var / `~/.claude/.credentials.json` |
| `src/conductor/providers/claude.py` (modify) | Accept `auth_token` in `__init__`, forward to `AsyncAnthropic` |
| `src/conductor/providers/factory.py` (modify) | Add `"claude-subscription"` case in `create_provider` |
| `src/conductor/config/schema.py` (modify) | Add `"claude-subscription"` to provider `Literal` annotations |
| `tests/test_providers/test_claude_credentials.py` (create) | Unit tests for credential discovery helper |
| `tests/test_providers/test_factory.py` (modify) | Tests for factory accepting `"claude-subscription"` |
| `tests/test_providers/test_claude.py` (modify) | Smoke test for `ClaudeProvider(auth_token=...)` |

---

### Task 1: Create credential discovery module

**Files:**
- Create: `src/conductor/providers/claude_credentials.py`

- [ ] **Step 1: Write the failing test for credential discovery**

```python
# tests/test_providers/test_claude_credentials.py

"""Unit tests for Claude credential discovery."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from conductor.exceptions import ProviderError
from conductor.providers.claude_credentials import resolve_auth_token


class TestResolveAuthToken:
    """Tests for resolve_auth_token()."""

    def test_explicit_kwarg_takes_priority(self) -> None:
        """Explicit auth_token kwarg should be returned regardless of env/file."""
        result = resolve_auth_token(auth_token="explicit-token")
        assert result == "explicit-token"

    def test_env_var_when_file_absent(self, tmp_path: Path) -> None:
        """ANTHROPIC_AUTH_TOKEN env var should be used when credentials file is missing."""
        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            tmp_path / "nonexistent.json",
        ):
            result = resolve_auth_token()
            assert result == "env-token"

    def test_env_var_takes_priority_over_file(self, tmp_path: Path) -> None:
        """ANTHROPIC_AUTH_TOKEN should take priority over credentials file."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"oauth_token": "file-token"}))

        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token()
            assert result == "env-token"

    def test_file_missing_and_env_unset_raises(self, tmp_path: Path) -> None:
        """When both file and env var are absent, raise ProviderError."""
        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            tmp_path / "nonexistent.json",
        ):
            with pytest.raises(ProviderError) as exc_info:
                resolve_auth_token()
            assert "claude login" in str(exc_info.value)
            assert "ANTHROPIC_AUTH_TOKEN" in str(exc_info.value)

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        """Malformed credentials file should raise ProviderError with file path."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text("not valid json {{{")

        with patch.dict(os.environ, {}, clear=True), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            with pytest.raises(ProviderError) as exc_info:
                resolve_auth_token()
            assert str(creds_file) in str(exc_info.value)

    def test_explicit_kwarg_overrides_env_and_file(self, tmp_path: Path) -> None:
        """Explicit auth_token kwarg takes priority over both env var and file."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"oauth_token": "file-token"}))

        with patch.dict(
            os.environ, {"ANTHROPIC_AUTH_TOKEN": "env-token"}, clear=True
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token(auth_token="explicit")
            assert result == "explicit"

    def test_never_reads_api_key_env(self, tmp_path: Path) -> None:
        """resolve_auth_token must never read ANTHROPIC_API_KEY."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"oauth_token": "file-token"}))

        with patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "should-be-ignored"},
            clear=True,
        ), patch(
            "conductor.providers.claude_credentials.CREDENTIALS_PATH",
            creds_file,
        ):
            result = resolve_auth_token()
            assert result == "file-token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_providers/test_claude_credentials.py -v`
Expected: All tests FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Write the credential discovery module**

```python
# src/conductor/providers/claude_credentials.py

"""Claude subscription credential discovery.

Resolves the OAuth bearer token for Claude Pro/Max subscriptions from one of:
1. Explicit ``auth_token`` kwarg
2. ``ANTHROPIC_AUTH_TOKEN`` environment variable
3. ``~/.claude/.credentials.json`` file

Never reads ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from conductor.exceptions import ProviderError

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


def resolve_auth_token(auth_token: str | None = None) -> str:
    """Resolve the Claude subscription bearer token.

    Priority order:
    1. Explicit ``auth_token`` kwarg
    2. ``ANTHROPIC_AUTH_TOKEN`` environment variable
    3. ``~/.claude/.credentials.json`` — parsed for the ``oauth_token`` field

    Args:
        auth_token: Explicit auth token. If provided, returned immediately.

    Returns:
        The resolved bearer token string.

    Raises:
        ProviderError: If no credentials are found, with the message
            "No subscription credentials found — run 'claude login' or set ANTHROPIC_AUTH_TOKEN".
        ProviderError: If the credentials file is present but contains
            malformed JSON, with the file path in the message.
    """
    if auth_token is not None:
        return auth_token

    env_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if env_token:
        return env_token

    if CREDENTIALS_PATH.exists():
        try:
            data = json.loads(CREDENTIALS_PATH.read_text())
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"Failed to parse Claude credentials file: {CREDENTIALS_PATH} — {exc}",
                suggestion="Re-run 'claude login' to regenerate the credentials file.",
            ) from exc
        token = data.get("oauth_token")
        if token:
            return token

    raise ProviderError(
        "No subscription credentials found — run 'claude login' or set ANTHROPIC_AUTH_TOKEN",
        suggestion="Run 'claude login' to authenticate with a Claude subscription, "
        "or set ANTHROPIC_AUTH_TOKEN if you have a token from another source.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_providers/test_claude_credentials.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_providers/test_claude_credentials.py src/conductor/providers/claude_credentials.py
git commit -m "feat: add Claude subscription credential discovery module"
```

---

### Task 2: Add auth_token support to ClaudeProvider

**Files:**
- Modify: `src/conductor/providers/claude.py` (__init__ and _initialize_client)

- [ ] **Step 1: Write the failing smoke test**

Append to `tests/test_providers/test_claude.py`:

```python
# --- Claude subscription auth_token smoke test ---

class TestClaudeProviderAuthToken:
    """Smoke tests for ClaudeProvider with auth_token."""

    @patch("conductor.providers.claude.AsyncAnthropic")
    @patch("conductor.providers.claude.anthropic")
    def test_auth_token_forwarded_to_sdk(
        self, mock_anthropic_module: Any, mock_async_anthropic: Any
    ) -> None:
        """ClaudeProvider(auth_token='test') forwards auth_token to AsyncAnthropic."""
        mock_anthropic_module.__version__ = "0.77.0"

        ClaudeProvider(api_key=None, auth_token="test-token")

        mock_async_anthropic.assert_called_once_with(
            auth_token="test-token",
            timeout=600.0,
        )

    @patch("conductor.providers.claude.AsyncAnthropic")
    @patch("conductor.providers.claude.anthropic")
    def test_api_key_is_none_when_auth_token_set(
        self, mock_anthropic_module: Any, mock_async_anthropic: Any
    ) -> None:
        """When auth_token is set, api_key should be forced to None."""
        mock_anthropic_module.__version__ = "0.77.0"

        ClaudeProvider(api_key="should-be-ignored", auth_token="test-token")

        _, kwargs = mock_async_anthropic.call_args
        assert kwargs["auth_token"] == "test-token"
        assert "api_key" not in kwargs or kwargs.get("api_key") is None

    @patch("conductor.providers.claude.AsyncAnthropic")
    @patch("conductor.providers.claude.anthropic")
    def test_original_api_key_path_unchanged(
        self, mock_anthropic_module: Any, mock_async_anthropic: Any
    ) -> None:
        """When only api_key is provided (no auth_token), existing behavior is preserved."""
        mock_anthropic_module.__version__ = "0.77.0"

        ClaudeProvider(api_key="my-api-key")

        mock_async_anthropic.assert_called_once_with(
            api_key="my-api-key",
            timeout=600.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_providers/test_claude.py::TestClaudeProviderAuthToken -v`
Expected: Tests FAIL because `_initialize_client()` doesn't pass `auth_token`

- [ ] **Step 3: Modify ClaudeProvider.__init__ and _initialize_client**

In `src/conductor/providers/claude.py`, modify `__init__` to accept `auth_token`:

```python
def __init__(
    self,
    api_key: str | None = None,
    auth_token: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 600.0,
    retry_config: RetryConfig | None = None,
    mcp_servers: dict[str, Any] | None = None,
    max_agent_iterations: int | None = None,
    max_session_seconds: float | None = None,
    default_reasoning_effort: ReasoningEffort | None = None,
) -> None:
```

Add this line after `self._api_key = api_key`:

```python
self._auth_token = auth_token
```

Modify `_initialize_client` to forward `auth_token`:

```python
def _initialize_client(self) -> None:
    """Initialize the Anthropic client and log SDK version."""
    if not ANTHROPIC_SDK_AVAILABLE or AsyncAnthropic is None:
        return

    kwargs: dict[str, Any] = {"timeout": self._timeout}
    if self._auth_token is not None:
        kwargs["auth_token"] = self._auth_token
    else:
        kwargs["api_key"] = self._api_key

    self._client = AsyncAnthropic(**kwargs)
    # ... (rest of method unchanged: SDK version logging follows)
```

Update `__init__` docstring to document the new parameter:

```
auth_token: OAuth bearer token for Claude subscription authentication.
    When set, ``api_key`` is forced to ``None`` so the SDK sends
    ``Authorization: Bearer <token>`` instead of ``x-api-key``.
    Defaults to None (use ANTHROPIC_API_KEY env var).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_providers/test_claude.py::TestClaudeProviderAuthToken -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run existing Claude tests to verify no regressions**

Run: `uv run pytest tests/test_providers/test_claude.py -v -x --timeout=60`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add src/conductor/providers/claude.py tests/test_providers/test_claude.py
git commit -m "feat: add auth_token support to ClaudeProvider for subscription auth"
```

---

### Task 3: Add claude-subscription case to factory

**Files:**
- Modify: `src/conductor/providers/factory.py`

- [ ] **Step 1: Write the failing factory tests**

Append to `tests/test_providers/test_factory.py`:

```python
class TestClaudeSubscriptionFactory:
    """Tests for claude-subscription provider in create_provider."""

    @patch(
        "conductor.providers.claude_credentials.resolve_auth_token",
        return_value="resolved-token",
    )
    @patch("conductor.providers.factory.ANTHROPIC_SDK_AVAILABLE", True)
    @patch("conductor.providers.claude.AsyncAnthropic")
    @patch("conductor.providers.claude.anthropic")
    @pytest.mark.asyncio
    async def test_claude_subscription_constructs_claude_provider(
        self,
        mock_anthropic_module: Any,
        mock_async_anthropic: Any,
        mock_resolve: Any,
    ) -> None:
        """claude-subscription should construct a ClaudeProvider with resolved token."""
        from unittest.mock import AsyncMock

        mock_anthropic_module.__version__ = "0.77.0"
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=MagicMock(data=[]))
        mock_async_anthropic.return_value = mock_client

        provider = await create_provider("claude-subscription", validate=False)

        assert provider.__class__.__name__ == "ClaudeProvider"
        mock_resolve.assert_called_once_with(auth_token=None)
        mock_async_anthropic.assert_called_once()
        call_kwargs = mock_async_anthropic.call_args.kwargs
        assert call_kwargs["auth_token"] == "resolved-token"
        assert "api_key" not in call_kwargs or call_kwargs.get("api_key") is None

    @patch(
        "conductor.providers.claude_credentials.resolve_auth_token",
        return_value="resolved-token",
    )
    @patch("conductor.providers.factory.ANTHROPIC_SDK_AVAILABLE", True)
    @patch("conductor.providers.claude.AsyncAnthropic")
    @patch("conductor.providers.claude.anthropic")
    @pytest.mark.asyncio
    async def test_claude_subscription_passes_all_kwargs(
        self,
        mock_anthropic_module: Any,
        mock_async_anthropic: Any,
        mock_resolve: Any,
    ) -> None:
        """claude-subscription should pass model, temperature, etc. to ClaudeProvider."""
        from unittest.mock import AsyncMock

        mock_anthropic_module.__version__ = "0.77.0"
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=MagicMock(data=[]))
        mock_async_anthropic.return_value = mock_client

        provider = await create_provider(
            "claude-subscription",
            validate=False,
            default_model="claude-sonnet-4-5",
            temperature=0.3,
            max_tokens=4096,
            timeout=300.0,
            max_session_seconds=120.0,
            max_agent_iterations=10,
        )

        assert provider is not None
        assert provider._default_model == "claude-sonnet-4-5"
        assert provider._default_temperature == 0.3
        assert provider._default_max_tokens == 4096
        assert provider._timeout == 300.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_providers/test_factory.py::TestClaudeSubscriptionFactory -v`
Expected: Tests FAIL with `ProviderError: Unknown provider: claude-subscription`

- [ ] **Step 3: Add claude-subscription case to create_provider**

In `src/conductor/providers/factory.py`:

1. Import the credential helper:

```python
from conductor.providers.claude_credentials import resolve_auth_token
```

2. Add `"claude-subscription"` to the `provider_type` `Literal`:

```python
async def create_provider(
    provider_type: Literal[
        "copilot", "openai-agents", "claude", "pydantic-deep", "claude-agent-sdk",
        "claude-subscription",
    ] = "copilot",
```

3. Add the new case after the `"claude"` case:

```python
        case "claude-subscription":
            if not ANTHROPIC_SDK_AVAILABLE:
                raise ProviderError(
                    "Claude provider requires anthropic SDK",
                    suggestion="Install with: uv add 'anthropic>=0.77.0,<1.0.0'",
                )
            token = resolve_auth_token()
            provider = ClaudeProvider(
                auth_token=token,
                model=default_model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout if timeout is not None else 600.0,
                mcp_servers=mcp_servers,
                max_agent_iterations=max_agent_iterations,
                max_session_seconds=max_session_seconds,
                default_reasoning_effort=default_reasoning_effort,
            )
```

4. Update the unknown-provider suggestion to include `claude-subscription`:

```python
        case _:
            raise ProviderError(
                f"Unknown provider: {provider_type}",
                suggestion="Valid providers are: copilot, openai-agents, claude, "
                "claude-subscription, pydantic-deep, claude-agent-sdk",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_providers/test_factory.py::TestClaudeSubscriptionFactory -v`
Expected: Both tests PASS

- [ ] **Step 5: Run existing factory tests to verify no regressions**

Run: `uv run pytest tests/test_providers/test_factory.py -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add src/conductor/providers/factory.py tests/test_providers/test_factory.py
git commit -m "feat: add claude-subscription provider to factory"
```

---

### Task 4: Update schema to accept claude-subscription

**Files:**
- Modify: `src/conductor/config/schema.py`

- [ ] **Step 1: Update the ProviderSettings name Literal**

In `src/conductor/config/schema.py`, update the `ProviderSettings.name` field:

```python
    name: Literal[
        "copilot", "openai-agents", "claude", "claude-agent-sdk", "claude-subscription"
    ] = "copilot"
```

- [ ] **Step 2: Update the AgentDef.provider Literal**

In the same file, update the `AgentDef.provider` field:

```python
    provider: Literal[
        "copilot", "claude", "pydantic-deep", "claude-agent-sdk", "claude-subscription"
    ] | None = None
```

- [ ] **Step 3: Update the RuntimeConfig.provider type if present**

Search for any other `Literal` that enumerates provider names in `schema.py` and add `"claude-subscription"`.

Run: `uv run grep -n "Literal\[.*claude.*claude-agent-sdk.*\]" src/conductor/config/schema.py`
Expected: Find the remaining places (if any) that need updating.

- [ ] **Step 4: Run existing validation tests**

Run: `uv run pytest tests/test_config/ -v -k "provider" --timeout=60`
Expected: All existing provider validation tests pass

- [ ] **Step 5: Run all tests to verify no regressions**

Run: `uv run pytest tests/ -x --timeout=120 -m "not performance" 2>&1 | tail -30`
Expected: All tests PASS (or same failures as before this change)

- [ ] **Step 6: Commit**

```bash
git add src/conductor/config/schema.py
git commit -m "feat: add claude-subscription to schema provider name enumerations"
```

---

### Task 5: End-to-end validation

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/test_providers/test_claude_credentials.py tests/test_providers/test_factory.py::TestClaudeSubscriptionFactory tests/test_providers/test_claude.py::TestClaudeProviderAuthToken -v`
Expected: All new tests PASS

- [ ] **Step 2: Run the full Claude test suite for regressions**

Run: `uv run pytest tests/test_providers/test_claude.py tests/test_providers/test_factory.py -v -x --timeout=120`
Expected: All tests PASS

- [ ] **Step 3: Verify conductor validate accepts the new provider**

Run: `printf "name: test\nagents:\n  - name: foo\n    prompt: hello\nruntime:\n  provider: claude-subscription\n" > /tmp/test-sub.yaml && uv run conductor validate /tmp/test-sub.yaml`
Expected: Validation succeeds (no errors about unknown provider)

- [ ] **Step 4: Commit** (if any fixups were needed)

```bash
git add -u
git commit -m "chore: final verification for claude-subscription provider"
```
