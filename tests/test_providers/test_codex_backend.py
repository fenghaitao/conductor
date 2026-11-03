"""Explicit Copilot routing, backend attestation, and native-default regressions."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from conductor.config.schema import AgentDef
from conductor.exceptions import ProviderError
from conductor.providers import codex as codex_mod
from conductor.providers.codex import CodexProvider
from conductor.providers.codex_backend import (
    backend_environment,
    backend_settings,
    config_overrides,
)

from .test_codex import sdk_stub as sdk_stub


@pytest.fixture
def catalog(tmp_path, monkeypatch, request):
    request.getfixturevalue("sdk_stub")
    path = tmp_path / "catalog.json"
    path.write_text('{"models": []}')
    monkeypatch.setenv("CONDUCTOR_CODEX_COPILOT_CATALOG", str(path))
    monkeypatch.delenv("CONDUCTOR_CODEX_BACKEND", raising=False)
    monkeypatch.delenv("COPILOT_PROXY_PORT", raising=False)
    monkeypatch.delenv("COPILOT_PROXY_API_KEY", raising=False)
    return path


def test_exact_overrides_and_default_key(catalog, monkeypatch):
    monkeypatch.setenv("COPILOT_PROXY_PORT", "4123")
    settings = backend_settings("copilot")
    overrides = dict(item.split("=", 1) for item in config_overrides(settings))
    assert {key: json.loads(value) for key, value in overrides.items()} == {
        "model_provider": "github_copilot",
        "model_providers.github_copilot.name": "GitHub Copilot via LiteLLM",
        "model_providers.github_copilot.base_url": "http://127.0.0.1:4123/v1",
        "model_providers.github_copilot.wire_api": "responses",
        "model_providers.github_copilot.env_key": "COPILOT_PROXY_API_KEY",
        "model_catalog_json": str(catalog),
        "web_search": "disabled",
    }
    assert backend_environment(settings)["COPILOT_PROXY_API_KEY"] == "sk-local-proxy"
    monkeypatch.setenv("COPILOT_PROXY_API_KEY", "private-test-value")
    assert backend_environment(settings)["COPILOT_PROXY_API_KEY"] == "private-test-value"
    assert "private-test-value" not in json.dumps(settings)


def test_native_default_and_unknown_backend(catalog):
    assert CodexProvider()._backend == "native"
    assert config_overrides(backend_settings("native")) == ()
    with pytest.raises(ProviderError, match="Unknown Codex backend"):
        CodexProvider(backend="copliot")


@pytest.mark.parametrize("port", ["no", "-1", "65536", "4000/v1", "１２"])
def test_bad_port_fails_closed(catalog, monkeypatch, port):
    monkeypatch.setenv("COPILOT_PROXY_PORT", port)
    with pytest.raises(ProviderError, match="COPILOT_PROXY_PORT"):
        backend_settings("copilot")


def test_catalog_required_and_frozen(catalog, monkeypatch):
    settings = backend_settings("copilot")
    catalog.write_text('{"models": [1]}')
    with pytest.raises(ProviderError, match="changed"):
        backend_environment(settings)
    monkeypatch.delenv("CONDUCTOR_CODEX_COPILOT_CATALOG")
    monkeypatch.delenv("AGENT_PROVIDERS_ROOT", raising=False)
    with pytest.raises(ProviderError, match="requires"):
        backend_settings("copilot")


def thread(provider="github_copilot", model="gpt-6.1-sol"):
    return SimpleNamespace(
        id="test-thread",
        read=AsyncMock(
            return_value=SimpleNamespace(
                thread=SimpleNamespace(model_provider=provider, model=model)
            )
        ),
        turn=AsyncMock(),
    )


def test_ensure_client_passes_overrides_and_env(catalog, monkeypatch):
    async def run():
        client = SimpleNamespace(__aenter__=AsyncMock())
        config = Mock(return_value="configured")
        factory = Mock(return_value=client)
        monkeypatch.setattr(codex_mod, "CodexConfig", config)
        monkeypatch.setattr(codex_mod, "AsyncCodex", factory)
        monkeypatch.setattr(codex_mod, "guard_startup", lambda *args: None)
        provider = CodexProvider(backend="copilot")
        await provider._ensure_client()
        await provider._ensure_client()
        assert config.call_count == factory.call_count == 1
        kwargs = config.call_args.kwargs
        assert 'model_provider="github_copilot"' in kwargs["config_overrides"]
        assert kwargs["env"]["COPILOT_PROXY_API_KEY"] == "sk-local-proxy"

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-6.1-sol"),
        (None, "gpt-6.1-sol"),
        ("github_copilot", "wrong"),
        ("github_copilot", None),
    ],
)
def test_wrong_session_rejected_before_turn(catalog, provider, model):
    async def run():
        p = CodexProvider(backend="copilot", model="gpt-6.1-sol")
        t = thread(provider, model)
        client = SimpleNamespace(thread_start=AsyncMock(return_value=t), account=AsyncMock())
        p._client = client
        with pytest.raises(ProviderError, match="mismatch"):
            await p.execute(AgentDef(name="proof", prompt="test"), {}, "test")
        t.turn.assert_not_called()
        assert client.thread_start.call_args.kwargs["model_provider"] == "github_copilot"

    asyncio.run(run())


def test_resume_backend_mismatch_does_not_start_fallback(catalog):
    async def run():
        p = CodexProvider(backend="copilot", model="gpt-6.1-sol")
        p.set_resume_session_ids({"proof": "native-thread"})
        p._client = SimpleNamespace(
            thread_resume=AsyncMock(return_value=thread("openai")), thread_start=AsyncMock()
        )
        with pytest.raises(ProviderError, match="mismatch"):
            await p.execute(AgentDef(name="proof", prompt="test"), {}, "test")
        p._client.thread_start.assert_not_called()

    asyncio.run(run())


def test_validate_uses_real_proxy_inference_not_chatgpt_account(catalog):
    async def run():
        p = CodexProvider(backend="copilot", model="gpt-6.1-sol")
        p._client = SimpleNamespace(
            thread_start=AsyncMock(return_value=thread()), account=AsyncMock()
        )
        p._run_turn = AsyncMock(
            return_value=SimpleNamespace(status="completed", final_response="OK")
        )
        assert await p.validate_connection()
        p._client.account.assert_not_called()
        p._run_turn.assert_awaited_once()
        p._run_turn.side_effect = ProviderError("proxy unavailable")
        with pytest.raises(ProviderError, match="proxy unavailable"):
            await p.validate_connection()
        p._client.account.assert_not_called()

    asyncio.run(run())


def test_validate_rejects_chatgpt_even_with_login(catalog):
    async def run():
        p = CodexProvider(backend="copilot", model="gpt-6.1-sol")
        p._client = SimpleNamespace(
            thread_start=AsyncMock(return_value=thread("openai")), account=AsyncMock()
        )
        p._run_turn = AsyncMock()
        with pytest.raises(ProviderError, match="mismatch"):
            await p.validate_connection()
        p._client.account.assert_not_called()
        p._run_turn.assert_not_called()

    asyncio.run(run())


def notification(name, **fields):
    return type(name, (), fields)()


class TurnHandle:
    id = "test-turn"

    def __init__(self, notes):
        self.notes = notes
        self.interrupt = AsyncMock()

    async def stream(self):
        for note in self.notes:
            yield note


def test_copilot_default_model_is_explicit_for_connection_probe(catalog):
    async def run():
        p = CodexProvider(backend="copilot")
        p._client = SimpleNamespace(thread_start=AsyncMock(return_value=thread()))
        p._run_turn = AsyncMock(
            return_value=SimpleNamespace(status="completed", final_response="OK")
        )
        assert await p.validate_connection()
        assert p._client.thread_start.call_args.kwargs["model"] == "gpt-6.1-sol"
        assert p._run_turn.call_args.kwargs["model"] == "gpt-6.1-sol"
        p._client.thread_start.return_value = thread(model=None)
        with pytest.raises(ProviderError, match="mismatch"):
            await p.validate_connection()

    asyncio.run(run())


@pytest.mark.parametrize("validation", [False, True])
@pytest.mark.parametrize("rerouted_model", ["another-model", None])
def test_model_reroute_rejected_despite_unchanged_thread_metadata(
    catalog, validation, rerouted_model
):
    async def run():
        p = CodexProvider(backend="copilot")
        t = thread()
        handle = TurnHandle(
            [
                notification(
                    "ModelReroutedNotification", to_model=rerouted_model, turn_id="test-turn"
                )
            ]
        )
        t.turn.return_value = handle
        p._client = SimpleNamespace(thread_start=AsyncMock(return_value=t))
        with pytest.raises(ProviderError, match="model rerouted"):
            if validation:
                await p.validate_connection()
            else:
                await p.execute(AgentDef(name="proof", prompt="test"), {}, "test")
        handle.interrupt.assert_awaited_once()

    asyncio.run(run())


def test_parse_recovery_cannot_accept_model_reroute(catalog):
    from conductor.config.schema import OutputField

    async def run():
        p = CodexProvider(backend="copilot")
        t = thread()
        first = TurnHandle(
            [
                notification(
                    "ItemCompletedNotification",
                    turn_id="test-turn",
                    item=SimpleNamespace(type="agentMessage", text="invalid JSON"),
                ),
                notification(
                    "TurnCompletedNotification",
                    turn=SimpleNamespace(status="completed", error=None),
                ),
            ]
        )
        second = TurnHandle(
            [
                notification(
                    "ModelReroutedNotification", to_model="another-model", turn_id="test-turn"
                )
            ]
        )
        t.turn.side_effect = [first, second]
        p._client = SimpleNamespace(thread_start=AsyncMock(return_value=t))
        with pytest.raises(ProviderError, match="model rerouted"):
            await p.execute(
                AgentDef(name="proof", prompt="test", output={"state": OutputField(type="string")}),
                {},
                "test",
            )
        assert t.turn.await_count == 2
        second.interrupt.assert_awaited_once()

    asyncio.run(run())


def test_unavailable_attestation_and_resume_errors_fail_closed(catalog):
    async def run():
        p = CodexProvider(backend="copilot")
        t = thread()
        t.read.side_effect = RuntimeError("no metadata")
        p._client = SimpleNamespace(
            thread_start=AsyncMock(return_value=t),
            thread_resume=AsyncMock(side_effect=RuntimeError("not resumable")),
        )
        with pytest.raises(ProviderError, match="Cannot attest"):
            await p.execute(AgentDef(name="proof", prompt="test"), {}, "test")
        t.turn.assert_not_called()
        p._client.thread_start.reset_mock()
        p.set_resume_session_ids({"proof": "missing"})
        with pytest.raises(ProviderError, match="no fallback"):
            await p.execute(AgentDef(name="proof", prompt="test"), {}, "test")
        p._client.thread_start.assert_not_called()

    asyncio.run(run())
