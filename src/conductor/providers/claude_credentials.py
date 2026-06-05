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

# Evaluated at import time. Tests must patch this name directly:
#   patch("conductor.providers.claude_credentials.CREDENTIALS_PATH", tmp_path / "creds.json")
# Patching HOME or Path.home after import has no effect.
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


def resolve_auth_token(auth_token: str | None = None) -> str:
    """Resolve the Claude subscription bearer token.

    Priority order:
    1. Explicit ``auth_token`` kwarg (must be a non-empty string)
    2. ``ANTHROPIC_AUTH_TOKEN`` environment variable
    3. ``~/.claude/.credentials.json`` — parsed for the ``oauth_token`` field

    Args:
        auth_token: Explicit auth token. If truthy, returned immediately.
            An empty string is treated as unset and falls through to env/file lookup.

    Returns:
        The resolved bearer token string.

    Raises:
        ProviderError: If no credentials are found, with the message
            "No subscription credentials found — run 'claude login' or set ANTHROPIC_AUTH_TOKEN".
        ProviderError: If the credentials file is present but contains
            malformed JSON, with the file path in the message.
        ProviderError: If the credentials file contains an empty ``oauth_token`` field.
    """
    if auth_token:
        return auth_token

    env_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if env_token:
        return env_token

    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"Failed to parse Claude credentials file: {CREDENTIALS_PATH} — {exc}",
            suggestion="Re-run 'claude login' to regenerate the credentials file.",
        ) from exc
    else:
        token = data.get("oauth_token")
        if token:
            return token
        if token == "":
            raise ProviderError(
                f"Claude credentials file has an empty oauth_token field: {CREDENTIALS_PATH}",
                suggestion="Re-run 'claude login' to regenerate the credentials file.",
            )

    raise ProviderError(
        "No subscription credentials found — run 'claude login' or set ANTHROPIC_AUTH_TOKEN",
        suggestion="Run 'claude login' to authenticate with a Claude subscription, "
        "or set ANTHROPIC_AUTH_TOKEN if you have a token from another source.",
    )
