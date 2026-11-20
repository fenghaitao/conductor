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

# Routed backends, mirroring agent-providers/launch.py. Each needs an explicit
# model catalog (a file in an agent-providers checkout, or its own variable).
#
# copilot       GitHub Copilot through the shared LiteLLM proxy (port 4000).
# cth-gemini    CTH Gemini through the agent-providers CTH service: its LiteLLM
#               Responses bridge (port 4101) and gateway refresh the CTH token.
#
# There is no CTH DeepSeek backend: CTH's content filter blocks Codex's
# multi-step tool use there. Use the copilot provider with a CTH profile.
ROUTES: dict[str, dict[str, str]] = {
    "copilot": {
        "model_provider": "github_copilot",
        "name": "GitHub Copilot via LiteLLM",
        "catalog_env": CATALOG_ENV,
        "catalog": "copilot/codex/codex_copilot_models.json",
        "default_model": "gpt-6.1-sol",
        "label": "Copilot",
    },
    "cth-gemini": {
        "model_provider": "cth_gemini",
        "name": "CTH Gemini via the agent-providers CTH service",
        "catalog_env": "CONDUCTOR_CODEX_CTH_GEMINI_CATALOG",
        "catalog": "cth/codex/codex_cth_gemini_models.json",
        "default_model": "gemini-4-argon",
        "label": "CTH Gemini",
    },
}
BACKENDS = ("native", *ROUTES)
CTH_SERVICE_KEY_ENV = "CTH_SERVICE_KEY"
CTH_SERVICE_KEY_FILE_ENV = "CTH_SERVICE_KEY_FILE"
CTH_SERVICE_BRIDGE_PORT_ENV = "CTH_SERVICE_BRIDGE_PORT"
# Every variable backend_environment may set or clear. A caller that launches
# a child with only part of the routed environment copies these (and removes
# those the routed environment lacks).
ROUTE_VARIABLES = (
    BACKEND_ENV,
    *(route["catalog_env"] for route in ROUTES.values()),
    "AGENT_PROVIDERS_ROOT",
    "COPILOT_PROXY_PORT",
    "COPILOT_PROXY_API_KEY",
    CTH_SERVICE_BRIDGE_PORT_ENV,
    CTH_SERVICE_KEY_FILE_ENV,
    CTH_SERVICE_KEY_ENV,
)


def resolve_backend(value: str | None = None) -> str:
    """Native remains the default; misspellings must not select ChatGPT."""
    backend = value if value is not None else os.environ.get(BACKEND_ENV, "native")
    if backend not in BACKENDS:
        raise ProviderError(f"Unknown Codex backend {backend!r}; use {', '.join(BACKENDS)}.")
    return backend


def default_model(backend: str) -> str | None:
    """Model for agents that name none; native keeps Codex's own default."""
    return ROUTES[backend]["default_model"] if backend in ROUTES else None


def backend_label(backend: str) -> str:
    return ROUTES[backend]["label"] if backend in ROUTES else "native Codex"


def _port(env: Mapping[str, str], name: str, default: str) -> str:
    port = env.get(name) or default
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ProviderError(f"{name} must be a port number from 1 to 65535.")
    return port


def _catalog(backend: str, env: Mapping[str, str]) -> tuple[str, str]:
    route = ROUTES[backend]
    catalog_value = env.get(route["catalog_env"])
    if not catalog_value and env.get("AGENT_PROVIDERS_ROOT"):
        catalog_value = str(Path(env["AGENT_PROVIDERS_ROOT"]) / route["catalog"])
    if not catalog_value:
        raise ProviderError(
            f"{route['label']} requires {route['catalog_env']} or AGENT_PROVIDERS_ROOT."
        )
    catalog = Path(catalog_value).expanduser().resolve()
    try:
        content = catalog.read_bytes()
        json.loads(content)
    except (OSError, ValueError) as exc:
        raise ProviderError(f"Cannot read {route['label']} model catalog {catalog}: {exc}") from exc
    return str(catalog), "sha256:" + hashlib.sha256(content).hexdigest()


def backend_settings(backend: str, env: Mapping[str, str] | None = None) -> dict:
    """Return public, freezeable routing settings (never credentials)."""
    backend = resolve_backend(backend)
    if backend == "native":
        return {"backend": "native"}
    env = os.environ if env is None else env
    route = ROUTES[backend]
    catalog, digest = _catalog(backend, env)
    settings: dict[str, Any] = {
        "backend": backend,
        "model_provider": route["model_provider"],
        "name": route["name"],
    }
    if backend == "copilot":
        port = _port(env, "COPILOT_PROXY_PORT", "4000")
        settings.update(base_url=f"http://127.0.0.1:{port}/v1", port=port)
    else:  # cth-gemini
        port = _port(env, CTH_SERVICE_BRIDGE_PORT_ENV, "4101")
        key_file = env.get(CTH_SERVICE_KEY_FILE_ENV)
        if not key_file and env.get("AGENT_PROVIDERS_ROOT"):
            key_file = str(Path(env["AGENT_PROVIDERS_ROOT"]) / ".cth-service-key")
        # The key file's path is public; its content is a credential read
        # only into the SDK child's environment.
        settings.update(
            base_url=f"http://127.0.0.1:{port}/v1",
            port=port,
            key_file=str(Path(key_file).expanduser().resolve()) if key_file else None,
        )
    settings.update(model_catalog_json=catalog, model_catalog_sha256=digest)
    return settings


def config_overrides(settings: dict) -> tuple[str, ...]:
    """Serialize the same TOML overrides as agent-providers/launch.py."""
    backend = settings["backend"]
    if backend == "native":
        return ()
    provider = settings["model_provider"]
    prefix = f"model_providers.{provider}"
    values: dict[str, Any] = {
        "model_provider": provider,
        f"{prefix}.name": settings["name"],
        f"{prefix}.base_url": settings["base_url"],
        f"{prefix}.wire_api": "responses",
    }
    if backend == "copilot":
        values[f"{prefix}.env_key"] = "COPILOT_PROXY_API_KEY"
    else:  # cth-gemini
        values[f"{prefix}.env_key"] = CTH_SERVICE_KEY_ENV
    values["model_catalog_json"] = settings["model_catalog_json"]
    values["web_search"] = "disabled"
    if backend == "cth-gemini":
        values["features.unified_exec"] = False
        # ChatGPT apps connectors add hundreds of tool definitions per request.
        values["features.apps"] = False
    return tuple(f"{key}={json.dumps(value)}" for key, value in values.items())


def _route_environment(settings: dict, env: dict[str, str]) -> None:
    """Point recomputation at the saved locations, not later ambient ones."""
    backend = settings["backend"]
    env[ROUTES[backend]["catalog_env"]] = settings["model_catalog_json"]
    if backend == "copilot":
        env["COPILOT_PROXY_PORT"] = settings["port"]
    elif backend == "cth-gemini":
        env[CTH_SERVICE_BRIDGE_PORT_ENV] = settings["port"]
        if settings["key_file"]:
            env[CTH_SERVICE_KEY_FILE_ENV] = settings["key_file"]
        else:
            env.pop(CTH_SERVICE_KEY_FILE_ENV, None)
            env.pop("AGENT_PROVIDERS_ROOT", None)


def _cth_service_key(settings: dict, env: Mapping[str, str]) -> str:
    if env.get(CTH_SERVICE_KEY_ENV):
        return env[CTH_SERVICE_KEY_ENV]
    if not settings["key_file"]:
        raise ProviderError(
            f"CTH Gemini requires {CTH_SERVICE_KEY_ENV} or a CTH service key file "
            f"({CTH_SERVICE_KEY_FILE_ENV} or AGENT_PROVIDERS_ROOT)."
        )
    try:
        key = Path(settings["key_file"]).read_text().strip()
    except OSError as exc:
        raise ProviderError(
            f"Cannot read the CTH service key {settings['key_file']}: {exc.strerror}. "
            "Start agent-providers' cth/service/cth_service.sh first."
        ) from exc
    if not key:
        raise ProviderError(f"The CTH service key file {settings['key_file']} is empty.")
    return key


def backend_environment(settings: dict) -> dict[str, str]:
    """Rehydrate saved routing, refusing catalog drift; keep secrets in env only."""
    backend = resolve_backend(settings["backend"])
    if backend == "native" and settings != {"backend": "native"}:
        raise ProviderError("Invalid saved native Codex backend settings")
    env = dict(os.environ)
    env[BACKEND_ENV] = backend
    if backend == "native":
        return env
    _route_environment(settings, env)
    if backend_settings(backend, env) != settings:
        raise ProviderError(
            f"Saved {backend_label(backend)} backend configuration or model catalog changed."
        )
    if backend == "copilot":
        env["COPILOT_PROXY_API_KEY"] = env.get("COPILOT_PROXY_API_KEY") or "sk-local-proxy"
    else:
        env[CTH_SERVICE_KEY_ENV] = _cth_service_key(settings, env)
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
