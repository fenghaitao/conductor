"""Explicit Codex inference routing; never infer a backend from login state."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from typing import Any

from conductor.exceptions import ProviderError

BACKEND_ENV = "CONDUCTOR_CODEX_BACKEND"
CATALOG_ENV = "CONDUCTOR_CODEX_COPILOT_CATALOG"
_START_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="conductor-codex-start")


def resolve_backend(value: str | None = None) -> str:
    """Native remains the default; misspellings must not select ChatGPT."""
    backend = value if value is not None else os.environ.get(BACKEND_ENV, "native")
    if backend not in {"native", "copilot"}:
        raise ProviderError(f"Unknown Codex backend {backend!r}; use native or copilot.")
    return backend


def backend_settings(backend: str, env: Mapping[str, str] | None = None) -> dict:
    """Return public, freezeable routing settings (never proxy credentials)."""
    backend = resolve_backend(backend)
    if backend == "native":
        return {"backend": "native"}
    env = os.environ if env is None else env
    catalog_value = env.get(CATALOG_ENV)
    if not catalog_value and env.get("AGENT_PROVIDERS_ROOT"):
        catalog_value = str(
            Path(env["AGENT_PROVIDERS_ROOT"]) / "copilot/codex/codex_copilot_models.json"
        )
    if not catalog_value:
        raise ProviderError(f"Copilot requires {CATALOG_ENV} or AGENT_PROVIDERS_ROOT.")
    catalog = Path(catalog_value).expanduser().resolve()
    try:
        content = catalog.read_bytes()
        json.loads(content)
    except (OSError, ValueError) as exc:
        raise ProviderError(f"Cannot read Copilot model catalog {catalog}: {exc}") from exc
    port = env.get("COPILOT_PROXY_PORT") or "4000"
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ProviderError("COPILOT_PROXY_PORT must be a port number from 1 to 65535.")
    return {
        "backend": "copilot",
        "model_provider": "github_copilot",
        "name": "GitHub Copilot via LiteLLM",
        "base_url": f"http://127.0.0.1:{port}/v1",
        "port": port,
        "model_catalog_json": str(catalog),
        "model_catalog_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
    }


def config_overrides(settings: dict) -> tuple[str, ...]:
    """Serialize the same TOML overrides as agent-providers/launch.py."""
    if settings["backend"] == "native":
        return ()
    values = {
        "model_provider": "github_copilot",
        "model_providers.github_copilot.name": settings["name"],
        "model_providers.github_copilot.base_url": settings["base_url"],
        "model_providers.github_copilot.wire_api": "responses",
        "model_providers.github_copilot.env_key": "COPILOT_PROXY_API_KEY",
        "model_catalog_json": settings["model_catalog_json"],
        "web_search": "disabled",
    }
    return tuple(f"{key}={json.dumps(value)}" for key, value in values.items())


def backend_environment(settings: dict) -> dict[str, str]:
    """Rehydrate saved routing, refusing catalog drift; keep secrets in env only."""
    env = dict(os.environ)
    env[BACKEND_ENV] = settings["backend"]
    if settings["backend"] == "copilot":
        env[CATALOG_ENV] = settings["model_catalog_json"]
        env["COPILOT_PROXY_PORT"] = settings["port"]
        if backend_settings("copilot", env) != settings:
            raise ProviderError("Saved Copilot backend configuration or model catalog changed.")
        env["COPILOT_PROXY_API_KEY"] = env.get("COPILOT_PROXY_API_KEY") or "sk-local-proxy"
    return env


def guard_startup(client: Any, config: Any) -> None:
    """Guard SDK 0.163 process creation, including cancellation before Popen returns.

    This is the one isolated SDK-internal compatibility boundary. Its async
    start() normally drops the executor future on cancellation. Keep that
    future outside the event loop's default executor and close its transport
    when an abandoned spawn eventually completes, even after the loop exits.
    """
    import asyncio

    from openai_codex.async_client import AsyncCodexClient  # ty: ignore[unresolved-import]

    transport = getattr(client, "_client", None)
    if not isinstance(transport, AsyncCodexClient):
        raise ProviderError("Unsupported Codex SDK transport; cannot guard Copilot startup")

    class StartupTransport(AsyncCodexClient):
        def __init__(self) -> None:
            super().__init__(config=config)
            self._close_lock = threading.Lock()

        def close_owned(self) -> None:
            # Both cancellation cleanup and the eventual-spawn callback may
            # close. SDK close itself is not safe for simultaneous callers.
            with self._close_lock:
                self._sync.close()

        async def start(self) -> None:
            operation = _START_EXECUTOR.submit(copy_context().run, self._sync.start)
            try:
                await asyncio.wrap_future(operation)
            except BaseException:

                def abandoned_spawn(_completed: object) -> None:
                    # No loop callback: this also runs after asyncio.run exits.
                    threading.Thread(
                        target=self.close_owned, daemon=True, name="conductor-codex-start-cleanup"
                    ).start()

                operation.add_done_callback(abandoned_spawn)
                raise

        async def close(self) -> None:
            await asyncio.to_thread(self.close_owned)

    client._client = StartupTransport()
