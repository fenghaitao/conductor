"""Explicit Copilot routing, backend attestation, and native-default regressions."""

import asyncio
import json
from pathlib import Path
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


def completed_turn(text="OK", status="completed"):
    return TurnHandle(
        [
            notification(
                "ItemCompletedNotification",
                turn_id="test-turn",
                item=SimpleNamespace(type="agentMessage", text=text),
            ),
            notification(
                "TurnCompletedNotification", turn=SimpleNamespace(status=status, error=None)
            ),
        ]
    )


@pytest.mark.parametrize("sandbox", [None, "workspace-write", "full-access"])
def test_validation_uses_disposable_read_only_thread_outside_workspace(
    catalog, tmp_path, monkeypatch, sandbox
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = workspace / "source.txt"
    sentinel.write_text("unchanged")
    monkeypatch.chdir(workspace)

    async def run():
        p = CodexProvider(backend="copilot", sandbox=sandbox, approval_mode="auto_review")
        original_sandbox = p._sandbox
        p.set_resume_session_ids({"connection_probe": "workflow-thread"})
        t = thread()

        async def turn(_input, **kwargs):
            assert kwargs["sandbox"].value == "read-only"
            assert Path(kwargs["cwd"]) != workspace
            assert list(Path(kwargs["cwd"]).iterdir()) == []
            return completed_turn()

        t.turn.side_effect = turn
        client = SimpleNamespace(thread_start=AsyncMock(return_value=t), thread_resume=AsyncMock())
        p._client = client
        assert await p.validate_connection()
        options = client.thread_start.call_args.kwargs
        assert options["sandbox"].value == "read-only"
        assert options["approval_mode"].value == "deny_all"
        assert options["ephemeral"] is True
        assert options["cwd"] == t.turn.call_args.kwargs["cwd"]
        assert not Path(options["cwd"]).exists()
        assert p._sandbox is original_sandbox
        assert p._restored_thread_ids == {"connection_probe": "workflow-thread"}
        client.thread_resume.assert_not_called()
        assert Path.cwd() == workspace and sentinel.read_text() == "unchanged"

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome", ["success", "resume-error", "catalog-drift", "wrong-route", "probe-failure"]
)
def test_checkpoint_resume_restores_copilot_before_any_inference(
    catalog, tmp_path, monkeypatch, outcome
):
    """Exercise real checkpoint I/O, CLI resume, registry and factory wiring."""
    from conductor.cli.run import resume_workflow_async
    from conductor.config.loader import load_config
    from conductor.engine.checkpoint import CheckpointManager
    from conductor.engine.workflow import WorkflowEngine
    from conductor.providers import factory
    from conductor.providers.registry import ProviderRegistry

    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("""workflow:
  name: codex-checkpoint
  entry_point: worker
  runtime:
    provider: codex
    default_model: gpt-6.1-sol
agents:
  - name: worker
    prompt: Continue the task.
    routes:
      - to: $end
output:
  result: "{{ worker.output.response }}"
""")
    monkeypatch.setenv("CONDUCTOR_TMPDIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CONDUCTOR_CODEX_BACKEND", "copilot")
    monkeypatch.setenv("COPILOT_PROXY_API_KEY", "original-secret")
    monkeypatch.setenv("COPILOT_PROXY_PORT", "4123")
    monkeypatch.setattr(factory, "CODEX_SDK_AVAILABLE", True)
    monkeypatch.setattr(codex_mod, "CodexConfig", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(codex_mod, "guard_startup", lambda *args: None)

    async def run():
        worker = thread()
        worker.turn.side_effect = (
            [completed_turn("resumed")]
            if outcome == "probe-failure"
            else [completed_turn(status="failed"), completed_turn("resumed")]
        )
        initial_run = True

        async def start(**kwargs):
            assert kwargs["model_provider"] == "github_copilot"
            if kwargs.get("ephemeral"):
                probe = thread()
                probe.turn.return_value = completed_turn(
                    status="failed" if outcome == "probe-failure" and initial_run else "completed"
                )
                return probe
            return worker

        client = SimpleNamespace(
            __aenter__=AsyncMock(),
            close=AsyncMock(),
            thread_start=AsyncMock(side_effect=start),
            thread_resume=AsyncMock(return_value=worker),
            account=AsyncMock(),
        )
        configs = []

        def make_client(config):
            assert config.env["CONDUCTOR_CODEX_BACKEND"] == "copilot"
            assert config.env["COPILOT_PROXY_PORT"] == "4123"
            configs.append(config)
            return client

        monkeypatch.setattr(codex_mod, "AsyncCodex", make_client)
        config = load_config(workflow)
        async with ProviderRegistry(config) as registry:
            engine = WorkflowEngine(config, registry=registry, workflow_path=workflow)
            with pytest.raises(ProviderError, match="failed"):
                await engine.run({})
        checkpoints = list((tmp_path / "runtime/checkpoints").glob("*.json"))
        assert len(checkpoints) == 1
        saved = CheckpointManager.load_checkpoint(checkpoints[0])
        settings = saved.provider_state["codex"]["backend_settings"]
        assert settings == backend_settings("copilot")
        assert saved.copilot_session_ids == (
            {} if outcome == "probe-failure" else {"worker": "test-thread"}
        )
        if outcome == "probe-failure":
            assert client.close.await_count >= 1
        assert "original-secret" not in checkpoints[0].read_text()
        initial_run = False

        for key in (
            "CONDUCTOR_CODEX_BACKEND",
            "CONDUCTOR_CODEX_COPILOT_CATALOG",
            "AGENT_PROVIDERS_ROOT",
            "COPILOT_PROXY_PORT",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("COPILOT_PROXY_API_KEY", "rotated-secret")
        if outcome == "catalog-drift":
            catalog.write_text('{"models": ["changed"]}')
        elif outcome == "resume-error":
            client.thread_resume.side_effect = RuntimeError("unreachable thread")
        elif outcome == "wrong-route":
            client.thread_resume.return_value = thread(provider="openai")
        if outcome in {"success", "probe-failure"}:
            result = await resume_workflow_async(
                checkpoint_path=checkpoints[0], no_interactive=True
            )
            assert result == {"result": "resumed"}
            assert configs[-1].env["COPILOT_PROXY_API_KEY"] == "rotated-secret"
        else:
            with pytest.raises(ProviderError, match="changed|no fallback|mismatch"):
                await resume_workflow_async(checkpoint_path=checkpoints[0], no_interactive=True)
        # Resume must never dispatch a fresh native thread, even on failure.
        starts = [
            call.kwargs
            for call in client.thread_start.call_args_list
            if not call.kwargs.get("ephemeral")
        ]
        assert len(starts) == 1
        if outcome not in {"catalog-drift", "probe-failure"}:
            assert client.thread_resume.call_args.kwargs["model_provider"] == "github_copilot"
        client.account.assert_not_called()
        assert worker.turn.await_count == (2 if outcome == "success" else 1)

    asyncio.run(run())


def test_native_checkpoint_ignores_later_copilot_environment(catalog, monkeypatch):
    saved = CodexProvider(backend="native").get_checkpoint_state()["codex"]
    monkeypatch.setenv("CONDUCTOR_CODEX_BACKEND", "copilot")
    monkeypatch.setenv("CONDUCTOR_CODEX_COPILOT_CATALOG", "/missing-catalog.json")
    restored = CodexProvider(checkpoint_state=saved)
    assert restored.get_checkpoint_state() == {"codex": saved}
    assert restored._backend == "native"


def test_uninstantiated_checkpoint_settings_survive_another_checkpoint(catalog):
    from conductor.config.schema import RuntimeConfig, WorkflowConfig, WorkflowDef
    from conductor.providers.registry import ProviderRegistry

    saved = {"codex": {"backend_settings": backend_settings("copilot")}}
    registry = ProviderRegistry(
        WorkflowConfig(
            workflow=WorkflowDef(
                name="resume", entry_point="worker", runtime=RuntimeConfig(provider="codex")
            ),
            agents=[AgentDef(name="worker", prompt="Continue")],
        )
    )
    registry.set_checkpoint_state(saved)
    retained = registry.get_checkpoint_state()
    assert retained == saved
    retained["codex"]["backend_settings"]["backend"] = "native"
    assert registry.get_checkpoint_state() == saved


def test_mixed_provider_checkpoint_preserves_both_sessions_and_resumes_codex_thread(
    catalog, tmp_path, monkeypatch
):
    from conductor.cli.run import resume_workflow_async
    from conductor.config.loader import load_config
    from conductor.engine.checkpoint import CheckpointManager
    from conductor.engine.workflow import WorkflowEngine
    from conductor.providers import factory
    from conductor.providers.copilot import CopilotProvider
    from conductor.providers.registry import ProviderRegistry

    workflow = tmp_path / "mixed.yaml"
    workflow.write_text("""workflow:
  name: mixed-provider-checkpoint
  entry_point: planner
  runtime:
    provider: codex
    default_model: gpt-6.1-sol
agents:
  - name: planner
    provider: copilot
    prompt: Prepare the plan.
    routes:
      - to: implementer
  - name: implementer
    provider: codex
    prompt: Continue the implementation.
    routes:
      - to: $end
output:
  result: "{{ implementer.output.response }}"
""")
    monkeypatch.setenv("CONDUCTOR_TMPDIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CONDUCTOR_CODEX_BACKEND", "copilot")
    monkeypatch.setattr(factory, "CODEX_SDK_AVAILABLE", True)
    monkeypatch.setattr(codex_mod, "CodexConfig", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(codex_mod, "guard_startup", lambda *args: None)
    planner_calls = []

    def plan(agent, _prompt, _context):
        planner_calls.append(agent.name)
        return {"plan": "prepared"}

    copilot = CopilotProvider(mock_handler=plan)
    # The native SDK session is simulated, while collection uses the real
    # Copilot provider's get_session_ids() method.
    copilot._session_ids["planner"] = "copilot-session-A"
    monkeypatch.setattr(factory, "CopilotProvider", lambda **kwargs: copilot)

    async def run():
        implementer = thread()
        implementer.id = "codex-thread-B"
        implementer.turn.side_effect = [
            completed_turn(status="failed"),
            completed_turn("continued"),
        ]

        async def start(**kwargs):
            assert kwargs["model_provider"] == "github_copilot"
            if kwargs.get("ephemeral"):
                probe = thread()
                probe.turn.return_value = completed_turn()
                return probe
            return implementer

        client = SimpleNamespace(
            __aenter__=AsyncMock(),
            close=AsyncMock(),
            thread_start=AsyncMock(side_effect=start),
            thread_resume=AsyncMock(return_value=implementer),
            account=AsyncMock(),
        )
        monkeypatch.setattr(codex_mod, "AsyncCodex", lambda config: client)
        config = load_config(workflow)
        async with ProviderRegistry(config) as registry:
            engine = WorkflowEngine(config, registry=registry, workflow_path=workflow)
            with pytest.raises(ProviderError, match="failed"):
                await engine.run({})
            assert list(registry.get_active_providers()) == ["copilot", "codex"]
        checkpoints = list((tmp_path / "runtime/checkpoints").glob("*.json"))
        assert len(checkpoints) == 1
        saved = CheckpointManager.load_checkpoint(checkpoints[0])
        assert saved.copilot_session_ids == {
            "planner": "copilot-session-A",
            "implementer": "codex-thread-B",
        }
        assert saved.context["agent_outputs"]["planner"] == {"plan": "prepared"}
        monkeypatch.delenv("CONDUCTOR_CODEX_BACKEND")
        monkeypatch.delenv("CONDUCTOR_CODEX_COPILOT_CATALOG")
        result = await resume_workflow_async(checkpoint_path=checkpoints[0], no_interactive=True)
        assert result == {"result": "continued"}
        assert client.thread_resume.call_args.args == ("codex-thread-B",)
        assert client.thread_resume.call_args.kwargs["model_provider"] == "github_copilot"
        assert planner_calls == ["planner"]
        client.account.assert_not_called()
        assert (
            len([c for c in client.thread_start.call_args_list if not c.kwargs.get("ephemeral")])
            == 1
        )

    asyncio.run(run())
