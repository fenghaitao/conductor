"""Unit tests for the CodexProvider implementation.

The ``openai-codex`` package is an optional extra, so every test here drives a
stubbed SDK rather than importing it. That is deliberate: the provider's own
contract — the tool-allowlist refusal, the reasoning-effort floor, the bare
(unwrapped) output schema, and the parse-recovery loop — is exactly the part
that must hold whether or not the extra is installed, and a suite that
``importorskip``s away would report all-clear on a machine that has never seen
the SDK.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from unittest.mock import patch

import pytest

from conductor.config.schema import AgentDef, OutputField
from conductor.exceptions import ProviderError, ValidationError
from conductor.providers import codex as codex_mod
from conductor.providers.codex import CodexProvider


class _Sandbox(str, Enum):
    read_only = "read-only"
    workspace_write = "workspace-write"
    full_access = "full-access"


class _ApprovalMode(str, Enum):
    deny_all = "deny_all"
    auto_review = "auto_review"


@dataclass
class _TextInput:
    text: str


@dataclass
class _SkillInput:
    name: str
    path: str


@dataclass
class _Breakdown:
    input_tokens: int = 100
    output_tokens: int = 5
    total_tokens: int = 105
    cached_input_tokens: int = 40
    cache_write_input_tokens: int = 0


@dataclass
class _Usage:
    """Mirrors ThreadTokenUsage: two nested breakdowns, no flat token fields."""

    total: _Breakdown = field(default_factory=_Breakdown)
    last: _Breakdown = field(default_factory=_Breakdown)


@dataclass
class _AgentMessageItem:
    text: str
    phase: Any = None
    type: str = "agentMessage"


@dataclass
class _Turn:
    status: str = "TurnStatus.completed"
    error: Any = None


class ItemCompletedNotification:
    def __init__(self, item: Any, turn_id: str) -> None:
        self.item = item
        self.turn_id = turn_id


class ThreadTokenUsageUpdatedNotification:
    def __init__(self, token_usage: Any, turn_id: str) -> None:
        self.token_usage = token_usage
        self.turn_id = turn_id


class TurnCompletedNotification:
    def __init__(self, turn: _Turn) -> None:
        self.turn = turn


@dataclass
class _Notification:
    payload: Any


def _turn_stream(text: str | None, turn_id: str, status: str = "TurnStatus.completed"):
    """Build the notification sequence a completed turn actually emits."""
    notes: list[_Notification] = []
    if text is not None:
        notes.append(
            _Notification(ItemCompletedNotification(_AgentMessageItem(text=text), turn_id))
        )
    notes.append(_Notification(ThreadTokenUsageUpdatedNotification(_Usage(), turn_id)))
    notes.append(_Notification(TurnCompletedNotification(_Turn(status=status))))
    return notes


class _TurnHandle:
    """Minimal AsyncTurnHandle stand-in.

    Deliberately exposes no ``run()``: the provider must collect the result
    from a single ``stream()`` pass, and a stub offering ``run()`` would hide
    a regression back to the double-consumption hang.
    """

    def __init__(self, notifications: list[_Notification], turn_id: str) -> None:
        self._notifications = notifications
        self.id = turn_id
        self.interrupted = False

    async def stream(self):
        for note in self._notifications:
            yield note

    async def interrupt(self) -> None:
        self.interrupted = True


class _Thread:
    """Minimal AsyncThread stand-in replaying a queue of turn responses."""

    def __init__(self, responses: list[str | None], thread_id: str = "th_1") -> None:
        self._responses = list(responses)
        self.id = thread_id
        self.turn_kwargs: list[dict[str, Any]] = []
        self.turn_inputs: list[Any] = []
        self.handles: list[_TurnHandle] = []

    async def turn(self, turn_input: Any, **kwargs: Any) -> _TurnHandle:
        self.turn_inputs.append(turn_input)
        self.turn_kwargs.append(kwargs)
        turn_id = f"turn_{len(self.handles)}"
        handle = _TurnHandle(_turn_stream(self._responses.pop(0), turn_id), turn_id)
        self.handles.append(handle)
        return handle


class _Client:
    def __init__(self, thread: _Thread) -> None:
        self._thread = thread
        self.start_calls = 0
        self.closed = False
        self.resumed: list[str] = []
        self.start_kwargs: dict[str, Any] = {}

    async def __aenter__(self) -> _Client:
        self.start_calls += 1
        return self

    async def close(self) -> None:
        self.closed = True

    async def account(self) -> dict[str, Any]:
        return {"account": "ok"}

    async def thread_start(self, **kwargs: Any) -> _Thread:
        self.start_kwargs = kwargs
        return self._thread

    async def thread_resume(self, thread_id: str, **kwargs: Any) -> _Thread:
        self.resumed.append(thread_id)
        return self._thread


@pytest.fixture
def sdk_stub():
    """Patch the module's SDK symbols so the provider is constructible."""
    with (
        patch.object(codex_mod, "CODEX_SDK_AVAILABLE", True),
        patch.object(codex_mod, "Sandbox", _Sandbox),
        patch.object(codex_mod, "ApprovalMode", _ApprovalMode),
        patch.object(codex_mod, "TextInput", _TextInput),
        patch.object(codex_mod, "SkillInput", _SkillInput),
    ):
        yield


def _agent(**kwargs: Any) -> AgentDef:
    base: dict[str, Any] = {"name": "researcher", "prompt": "Do the thing."}
    base.update(kwargs)
    return AgentDef(**base)


async def _run(provider: CodexProvider, agent: AgentDef, **kwargs: Any):
    return await provider.execute(agent=agent, context={}, rendered_prompt="go", **kwargs)


class TestAvailabilityGuard:
    def test_missing_sdk_raises_with_install_hint(self) -> None:
        with (
            patch.object(codex_mod, "CODEX_SDK_AVAILABLE", False),
            pytest.raises(ProviderError) as exc,
        ):
            CodexProvider()
        assert "openai-codex" in str(exc.value)
        assert exc.value.suggestion is not None


class TestCapabilityHonesty:
    """The descriptor is a contract; these pin the claims the design rests on."""

    def test_no_tool_passthrough(self) -> None:
        assert CodexProvider.CAPABILITIES.workflow_tools_passthrough is False

    def test_structured_output_declared_prompt_injection(self) -> None:
        # output_schema constrains but does not guarantee, and nothing is
        # pre-parsed — declaring "native" would overstate the guarantee.
        assert CodexProvider.CAPABILITIES.structured_output == "prompt_injection"

    def test_reasoning_effort_covers_every_conductor_level(self) -> None:
        # The SDK enum's names stop at xhigh, but it is open (`_missing_`)
        # and `models()` advertises `max` for the default model, so declaring
        # a narrower tuple would refuse an effort Codex actually accepts.
        assert set(CodexProvider.CAPABILITIES.reasoning_effort or ()) == {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }

    def test_plugins_unsupported(self) -> None:
        assert CodexProvider.CAPABILITIES.plugins is False

    def test_mcp_tools_false_because_nothing_is_forwarded(self) -> None:
        # The flag means "the workflow's configured MCP servers are
        # forwarded". Conductor does not translate them into Codex's config
        # shape, so declaring True would overstate what reaches the model.
        assert CodexProvider.CAPABILITIES.mcp_tools is False


class TestSandboxAndApprovalCoercion:
    def test_defaults_to_deny_all(self, sdk_stub: None) -> None:
        # An unattended run has nobody to answer an approval prompt.
        assert CodexProvider()._approval_mode is _ApprovalMode.deny_all

    def test_unknown_sandbox_refused(self, sdk_stub: None) -> None:
        with pytest.raises(ProviderError) as exc:
            CodexProvider(sandbox="wide-open")
        assert "wide-open" in str(exc.value)

    def test_known_sandbox_accepted(self, sdk_stub: None) -> None:
        assert CodexProvider(sandbox="read-only")._sandbox is _Sandbox.read_only


class TestToolAllowlistRefusal:
    """Codex scopes tools by sandbox; an allowlist has nothing to apply to."""

    async def test_non_empty_allowlist_refused(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        with pytest.raises(ProviderError) as exc:
            await _run(provider, _agent(tools=["search"]), tools=["search"])
        assert "sandbox" in exc.value.suggestion.lower()

    async def test_explicit_empty_allowlist_also_refused(self, sdk_stub: None) -> None:
        # Unlike claude-agent-sdk, `tools: []` has no Codex expression either:
        # read-only is a different promise, not an equivalent one.
        provider = CodexProvider()
        with pytest.raises(ProviderError):
            await _run(provider, _agent(tools=[]), tools=[])

    async def test_omitted_allowlist_passes(self, sdk_stub: None) -> None:
        # The raw agent.tools field is what carries the omitted signal, so an
        # executor-resolved [] must not be mistaken for an explicit opt-out.
        provider = CodexProvider()
        thread = _Thread(["hello"])
        provider._client = _Client(thread)
        out = await _run(provider, _agent(), tools=[])
        assert out.content == {"response": "hello"}


class TestReasoningEffort:
    async def test_max_forwarded(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["ok"])
        provider._client = _Client(thread)
        await _run(provider, _agent(reasoning={"effort": "max"}))
        assert thread.turn_kwargs[0]["effort"] == "max"

    async def test_unrecognised_effort_rejected_at_execute_time(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        agent = _agent.__wrapped__() if hasattr(_agent, "__wrapped__") else _agent()
        object.__setattr__(agent, "reasoning", type("R", (), {"effort": "turbo"})())
        with pytest.raises(ValidationError) as exc:
            await _run(provider, agent)
        assert "turbo" in str(exc.value)

    async def test_defaults_to_high_when_nothing_declared(self, sdk_stub: None) -> None:
        """Codex's own model default is `low`, which is too shallow here."""
        provider = CodexProvider()
        thread = _Thread(["ok"])
        provider._client = _Client(thread)
        agent = _agent()
        assert agent.reasoning is None
        await _run(provider, agent)
        assert thread.turn_kwargs[0]["effort"] == "high"

    async def test_workflow_default_beats_provider_default(self, sdk_stub: None) -> None:
        provider = CodexProvider(default_reasoning_effort="low")
        thread = _Thread(["ok"])
        provider._client = _Client(thread)
        await _run(provider, _agent())
        assert thread.turn_kwargs[0]["effort"] == "low"

    async def test_agent_effort_beats_both_defaults(self, sdk_stub: None) -> None:
        provider = CodexProvider(default_reasoning_effort="low")
        thread = _Thread(["ok"])
        provider._client = _Client(thread)
        await _run(provider, _agent(reasoning={"effort": "medium"}))
        assert thread.turn_kwargs[0]["effort"] == "medium"

    async def test_xhigh_forwarded(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["ok"])
        provider._client = _Client(thread)
        await _run(provider, _agent(reasoning={"effort": "xhigh"}))
        assert thread.turn_kwargs[0]["effort"] == "xhigh"


class TestOutputSchema:
    def test_schema_is_bare_not_wrapped(self, sdk_stub: None) -> None:
        """Codex wants a JSON Schema document, not claude-agent-sdk's wrapper."""
        provider = CodexProvider()
        schema = provider._build_output_schema({"answer": OutputField(type="string")})
        assert schema["type"] == "object"
        assert "json_schema" not in schema
        assert schema["required"] == ["answer"]
        assert schema["properties"]["answer"]["type"] == "string"

    async def test_schema_passed_on_every_turn(self, sdk_stub: None) -> None:
        # output_schema lives on the turn, not the thread, so it must be
        # re-sent each time rather than configured once.
        provider = CodexProvider()
        thread = _Thread(['{"answer": "42"}'])
        provider._client = _Client(thread)
        await _run(provider, _agent(output={"answer": OutputField(type="string")}))
        assert "output_schema" in thread.turn_kwargs[0]


class TestStructuredOutputParsing:
    async def test_valid_json_parsed(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(['{"answer": "42"}'])
        provider._client = _Client(thread)
        out = await _run(provider, _agent(output={"answer": OutputField(type="string")}))
        assert out.content == {"answer": "42"}

    async def test_no_schema_wraps_raw_text(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["just prose"])
        provider._client = _Client(thread)
        out = await _run(provider, _agent())
        assert out.content == {"response": "just prose"}

    async def test_unparseable_response_recovers_in_session(self, sdk_stub: None) -> None:
        """A schema violation is not a typed error, so it must be re-prompted."""
        provider = CodexProvider()
        thread = _Thread(["I think the answer is 42.", '{"answer": "42"}'])
        provider._client = _Client(thread)
        out = await _run(provider, _agent(output={"answer": OutputField(type="string")}))
        assert out.content == {"answer": "42"}
        # The recovery turn reuses the same thread rather than opening a new one.
        assert len(thread.turn_kwargs) == 2

    async def test_recovery_budget_exhausted_raises(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["nope" for _ in range(5)])
        provider._client = _Client(thread)
        with pytest.raises((ValidationError, ProviderError)):
            await _run(provider, _agent(output={"answer": OutputField(type="string")}))

    async def test_recovery_emits_event(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["prose", '{"answer": "42"}'])
        provider._client = _Client(thread)
        events: list[tuple[str, dict[str, Any]]] = []
        await _run(
            provider,
            _agent(output={"answer": OutputField(type="string")}),
            event_callback=lambda t, d: events.append((t, d)),
        )
        assert any(t == "agent_parse_recovery" for t, _ in events)


class TestSessionContinuity:
    def test_session_ids_are_namespaced(self, sdk_stub: None) -> None:
        # The engine merges every provider's map into one flat field, and
        # our keys are author-chosen names that collide with Copilot's.
        provider = CodexProvider()
        provider._thread_ids["investigate"] = "th_9"
        assert provider.get_session_ids() == {"codex:investigate": "th_9"}

    def test_restore_ignores_other_providers_keys(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        provider.set_resume_session_ids({"codex:a": "th_1", "claude-agent-sdk:b": "x"})
        assert provider._restored_thread_ids == {"a": "th_1"}

    async def test_keyed_agent_resumes_recorded_thread(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["ok"])
        client = _Client(thread)
        provider._client = client
        provider.set_resume_session_ids({"codex:probe": "th_prior"})
        await _run(provider, _agent(session_key="probe"))
        assert client.resumed == ["th_prior"]

    async def test_unresumable_thread_falls_back_to_fresh(self, sdk_stub: None) -> None:
        """A pruned thread must not fail the run."""
        provider = CodexProvider()
        thread = _Thread(["ok"])
        client = _Client(thread)

        async def boom(thread_id: str, **kwargs: Any):
            raise RuntimeError("no such thread")

        client.thread_resume = boom  # type: ignore[assignment]
        provider._client = client
        provider.set_resume_session_ids({"codex:probe": "gone"})
        out = await _run(provider, _agent(session_key="probe"))
        assert out.content == {"response": "ok"}


class TestSkillsAsTurnInput:
    async def test_skills_become_skill_inputs(self, sdk_stub: None) -> None:
        """Codex takes (name, path) pairs inline, not a directory list."""
        provider = CodexProvider()
        thread = _Thread(["ok"])
        provider._client = _Client(thread)
        await _run(provider, _agent(), skill_directories=["/tmp/skills/research"])
        items = thread.turn_inputs[0]
        assert isinstance(items[0], _TextInput)
        assert items[1] == _SkillInput(name="research", path="/tmp/skills/research")

    def test_declares_native_skills(self, sdk_stub: None) -> None:
        assert CodexProvider().supports_native_skills is True


class TestToolEvents:
    """Tool events must use the key every other provider emits."""

    def test_shell_command_is_named_and_carries_the_command(self) -> None:
        from conductor.providers.codex import _describe_tool_item

        payload = type(
            "P",
            (),
            {"command": "python3 -c 'print(1)'", "aggregated_output": "1\n", "status": "completed"},
        )()
        name, args, result = _describe_tool_item("commandExecution", payload)
        assert name == "shell"
        assert args == "python3 -c 'print(1)'"
        assert result == "1\n"

    def test_mcp_call_is_qualified_by_server(self) -> None:
        from conductor.providers.codex import _describe_tool_item

        payload = type(
            "P",
            (),
            {
                "server": "ado",
                "tool": "list_items",
                "arguments": "{}",
                "error": None,
                "status": "completed",
            },
        )()
        name, _, _ = _describe_tool_item("mcpToolCall", payload)
        assert name == "ado/list_items"

    def test_events_use_tool_name_not_tool(self) -> None:
        """`tool` renders as "unknown" in the console subscriber."""
        provider = CodexProvider.__new__(CodexProvider)
        events: list[tuple[str, dict[str, Any]]] = []
        item = _AgentMessageItem(text="")
        object.__setattr__(item, "type", "commandExecution")
        object.__setattr__(item, "command", "ls")
        provider._emit_item_events(item, lambda t, d: events.append((t, d)))
        assert [t for t, _ in events] == ["agent_tool_start", "agent_tool_complete"]
        assert all("tool_name" in d for _, d in events)
        assert events[0][1]["tool_name"] == "shell"


class TestPluginRefusal:
    async def test_custom_agents_refused(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        with pytest.raises(ProviderError) as exc:
            await _run(provider, _agent(), custom_agents=[{"name": "x"}])
        assert "plugins" in str(exc.value).lower()


class TestInterrupt:
    async def test_interrupt_signal_stops_the_turn(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        thread = _Thread(["partial"])
        provider._client = _Client(thread)
        signal = asyncio.Event()
        signal.set()
        out = await _run(provider, _agent(), interrupt_signal=signal)
        # The message that arrived before the break is preserved, not
        # discarded -- an interrupt returns partial output, not nothing.
        assert out.content == {"response": "partial"}
        assert out.partial is True
        assert thread.handles[0].interrupted is True


class TestLifecycle:
    async def test_client_started_once(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        client = _Client(_Thread([]))
        with (
            patch.object(codex_mod, "AsyncCodex", lambda _cfg: client),
            patch.object(codex_mod, "CodexConfig", lambda: None),
        ):
            await provider._ensure_client()
            await provider._ensure_client()
        assert client.start_calls == 1

    async def test_close_is_idempotent(self, sdk_stub: None) -> None:
        provider = CodexProvider()
        client = _Client(_Thread([]))
        provider._client = client
        await provider.close()
        await provider.close()
        assert client.closed is True
