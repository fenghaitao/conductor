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
    if auth_token:
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
