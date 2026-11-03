"""Exercise cancellation against the supported SDK's real transport internals.

Only transport initialization and process creation are replaced. No process,
model inference or credentials are used. CI installs the Codex extra separately.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("openai_codex")

from openai_codex import client as sdk

from conductor.exceptions import ProviderError
from conductor.providers.codex import CodexProvider
from conductor.providers.codex_backend import guard_startup


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text('{"models": []}')
    monkeypatch.setenv("CONDUCTOR_CODEX_COPILOT_CATALOG", str(path))
    return path


def startup_timeout():
    async def run():
        provider = CodexProvider(backend="copilot")
        try:
            await asyncio.wait_for(provider._ensure_client(), timeout=0.05)
        finally:
            await provider.close()

    return asyncio.run(run())


def test_unknown_transport_is_refused():
    with pytest.raises(ProviderError, match="Unsupported Codex SDK transport"):
        guard_startup(SimpleNamespace(_client=object()), None)


def test_cancellation_closes_partially_initialized_transport(catalog, monkeypatch):
    started = threading.Event()
    released = threading.Event()

    def initialize(client):
        started.set()
        released.wait(timeout=2)
        raise RuntimeError("initialization transport closed")

    def close(client):
        released.set()

    monkeypatch.setattr(sdk.CodexClient, "start", lambda client: None)
    monkeypatch.setattr(sdk.CodexClient, "initialize", initialize)
    monkeypatch.setattr(sdk.CodexClient, "close", close)
    before = time.monotonic()
    with pytest.raises(TimeoutError):
        startup_timeout()
    assert started.is_set() and released.is_set()
    assert time.monotonic() - before < 1


def test_cancellation_reaps_delayed_process_creation_after_loop_exits(catalog, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class Process:
        stdin = None

        def terminate(self):
            closed.set()

        def wait(self, timeout):
            return 0

    def delayed_popen(*args, **kwargs):
        entered.set()
        release.wait(timeout=2)
        return Process()

    monkeypatch.setattr(sdk.subprocess, "Popen", delayed_popen)
    monkeypatch.setattr(sdk.CodexClient, "_start_reader_thread", lambda client: None)
    monkeypatch.setattr(sdk.CodexClient, "_start_stderr_drain_thread", lambda client: None)
    before = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            startup_timeout()
        assert entered.is_set()
        assert time.monotonic() - before < 1
    finally:
        release.set()
    assert closed.wait(timeout=1), "abandoned spawn survived the event loop"
