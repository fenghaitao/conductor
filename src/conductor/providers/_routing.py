"""Shared provider-routing helpers.

Small endpoint-classification utilities used by more than one provider so the
logic lives in one place instead of being duplicated (or cross-imported)
between ``claude.py`` and ``copilot.py``.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def endpoint_requires_bearer_auth(base_url: str | None) -> bool:
    """Return True for anthropic-wire endpoints that require ``Authorization: Bearer``.

    Most anthropic-wire endpoints (the native Anthropic API, DeepSeek's
    ``/anthropic`` API) accept the ``x-api-key`` header that providers send for
    a configured ``api_key``. Volcengine Ark (DeepSeek served via Ark) is the
    exception: it rejects ``x-api-key`` with HTTP 401 and only accepts a Bearer
    token. So when an ``api_key`` is configured for an Ark ``base_url`` the
    provider presents it as a Bearer credential instead. This lets provider
    profiles stay uniform (always ``api_key``) while routing Ark correctly under
    the hood. See ``examples/providers/ark.yaml`` and ``claude-ark.yaml``.

    Args:
        base_url: The configured endpoint URL, or ``None``.

    Returns:
        True if the endpoint is a Volcengine Ark host.
    """
    if not base_url:
        return False
    try:
        host = (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return False
    # Volcengine Ark regional hosts are all ``ark.<region>.volces.com``.
    return host == "volces.com" or host.endswith(".volces.com")
