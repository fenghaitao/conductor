"""Tests for Copilot session-id propagation onto AgentOutput.

Conductor tracks Copilot session ids internally (``CopilotProvider._session_ids``,
surfaced via ``get_session_ids()``) but historically routed them only into the
on-failure checkpoint — never onto a successful ``AgentOutput`` or a workflow
event. A caller with no access to Conductor's internals (a script step in a
workflow, an external collector) had no way to learn which Copilot CLI session
backed a given agent step short of scanning ``~/.copilot/session-state/`` and
guessing from timestamps and cwd.

This closes that gap: every ``SDKResponse`` and ``AgentOutput`` the Copilot
provider returns now carries ``session_id`` (``None`` when the provider has no
real SDK session, e.g. the mock-handler path). ``session_id`` is read exactly
once, in ``_send_and_wait`` — the only method with the actual ``session``
object in hand — then copied through every downstream reconstruction. These
tests assert both the single read point and every copy site, since a session
id that goes stale after being copied through a retry or recovery loop would
be a very quiet bug: it fails only in the sense of pointing at the wrong
transcript, never by raising.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from conductor.config.schema import AgentDef, OutputField
from conductor.providers.base import AgentOutput
from conductor.providers.copilot import CopilotProvider, SDKResponse
from tests.test_providers.test_copilot_interrupt import FakeEvent, FakeSession


def _make_agent(name: str = "test_agent", **kw: Any) -> AgentDef:
    return AgentDef(name=name, model="gpt-4o", prompt="Test prompt", **kw)


def _deliver_idle_after_send(session: FakeSession) -> None:
    """Patch `session.send` so the normal (non-interrupt) idle path resolves,
    matching the pattern already used throughout test_copilot_interrupt.py."""
    original_send = session.send

    async def send_with_idle(data: Any) -> None:
        await original_send(data)
        await asyncio.sleep(0.01)
        session._callback(FakeEvent("session.idle"))

    session.send = send_with_idle


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_agent_output_session_id_defaults_to_none(self) -> None:
        output = AgentOutput(content={}, raw_response="")
        assert output.session_id is None

    def test_sdk_response_session_id_defaults_to_none(self) -> None:
        response = SDKResponse(content="x")
        assert response.session_id is None

    @pytest.mark.asyncio
    async def test_mock_handler_path_has_no_session_id(self) -> None:
        """The mock-handler path never creates a real SDK session, so there is
        nothing to report — this must stay None, not a fabricated value."""
        provider = CopilotProvider(mock_handler=lambda a, p, c: {"result": "x"})
        output = await provider.execute(_make_agent(), {}, "prompt")
        assert output.session_id is None


# ---------------------------------------------------------------------------
# The single read point: _send_and_wait
# ---------------------------------------------------------------------------


class TestSendAndWaitCapturesSessionId:
    @pytest.mark.asyncio
    async def test_normal_completion_carries_session_id(self) -> None:
        provider = CopilotProvider(mock_handler=lambda a, p, c: {})
        session = FakeSession(response_content="normal response")
        session.session_id = "sess-normal-001"
        _deliver_idle_after_send(session)

        result = await provider._send_and_wait(session, "prompt", False, False)

        assert result.session_id == "sess-normal-001"

    @pytest.mark.asyncio
    async def test_interrupted_partial_response_still_carries_session_id(self) -> None:
        """The interrupt/partial branch is a separate return statement in
        _send_and_wait — easy to update one and forget the other."""
        provider = CopilotProvider(mock_handler=lambda a, p, c: {})
        session = FakeSession(response_content="partial response", has_abort=True)
        session.session_id = "sess-partial-002"

        interrupt = asyncio.Event()
        interrupt.set()

        result = await provider._send_and_wait(
            session, "prompt", False, False, interrupt_signal=interrupt
        )

        assert result.partial is True
        assert result.session_id == "sess-partial-002"

    @pytest.mark.asyncio
    async def test_session_without_session_id_attribute_yields_none(self) -> None:
        """A session object with no `session_id` attribute at all (an SDK
        contract change, or an unusually minimal test double) must not raise —
        getattr's default is what makes this safe."""
        provider = CopilotProvider(mock_handler=lambda a, p, c: {})
        session = FakeSession(response_content="normal response")
        del session.session_id
        _deliver_idle_after_send(session)

        result = await provider._send_and_wait(session, "prompt", False, False)

        assert result.session_id is None


# ---------------------------------------------------------------------------
# Every copy site downstream of _send_and_wait
# ---------------------------------------------------------------------------


class TestExecuteEndToEndCarriesSessionId:
    """`execute()` -> `_execute_with_retry()` -> `_execute_sdk_call()` ->
    `_send_and_wait()`. These exercise the full chain, which is what an
    actual workflow run does."""

    @pytest.mark.asyncio
    async def test_no_output_schema_path_carries_session_id(self) -> None:
        """Agent has no `output:` schema -> _execute_sdk_call's early-return
        branch (the `if not agent.output:` SDKResponse construction)."""
        session = FakeSession(response_content="plain text reply")
        session.session_id = "sess-no-schema-003"
        _deliver_idle_after_send(session)

        provider = CopilotProvider()
        provider._client = AsyncMock()
        provider._client.create_session = AsyncMock(return_value=session)
        provider._client.start = AsyncMock()
        provider._started = True

        agent = _make_agent("plain")  # no output= -> no schema

        with (
            patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
            patch("conductor.cli.app.is_verbose", return_value=False),
            patch("conductor.cli.app.is_full", return_value=False),
        ):
            output = await provider.execute(agent, {}, "do work")

        assert output.session_id == "sess-no-schema-003"
        assert output.content == {"result": "plain text reply"}

    @pytest.mark.asyncio
    async def test_structured_output_path_carries_session_id(self) -> None:
        """Agent HAS an `output:` schema -> the JSON-parse-success branch."""
        session = FakeSession(response_content=json.dumps({"val": "ok"}))
        session.session_id = "sess-structured-004"
        _deliver_idle_after_send(session)

        provider = CopilotProvider()
        provider._client = AsyncMock()
        provider._client.create_session = AsyncMock(return_value=session)
        provider._client.start = AsyncMock()
        provider._started = True

        agent = _make_agent("structured", output={"val": OutputField(type="string")})

        with (
            patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
            patch("conductor.cli.app.is_verbose", return_value=False),
            patch("conductor.cli.app.is_full", return_value=False),
        ):
            output = await provider.execute(agent, {}, "do work")

        assert output.session_id == "sess-structured-004"
        assert output.content == {"val": "ok"}

    @pytest.mark.asyncio
    async def test_partial_output_from_execute_carries_session_id(self) -> None:
        """The interrupted-session early-return inside _execute_sdk_call
        (before the recovery loop is ever reached)."""
        session = FakeSession(response_content="partial reply", has_abort=True)
        session.session_id = "sess-partial-exec-005"

        provider = CopilotProvider()
        provider._client = AsyncMock()
        provider._client.create_session = AsyncMock(return_value=session)
        provider._client.start = AsyncMock()
        provider._started = True

        agent = _make_agent("interruptible")
        interrupt = asyncio.Event()
        interrupt.set()

        with (
            patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
            patch("conductor.cli.app.is_verbose", return_value=False),
            patch("conductor.cli.app.is_full", return_value=False),
        ):
            output = await provider.execute(agent, {}, "do work", interrupt_signal=interrupt)

        assert output.partial is True
        assert output.session_id == "sess-partial-exec-005"

    @pytest.mark.asyncio
    async def test_resumed_session_carries_its_own_session_id(self) -> None:
        """Resuming a prior session must report the RESUMED session's id, not
        the caller-supplied hint that triggered the resume — the two can
        legitimately differ if the SDK reissues an id on resume."""
        session = FakeSession(response_content=json.dumps({"val": "resumed"}))
        session.session_id = "sess-actually-resumed-006"
        _deliver_idle_after_send(session)

        provider = CopilotProvider()
        provider._client = AsyncMock()
        provider._client.resume_session = AsyncMock(return_value=session)
        provider._client.start = AsyncMock()
        provider._started = True
        provider.set_resume_session_ids({"researcher": "sess-stale-hint"})

        agent = _make_agent("researcher", output={"val": OutputField(type="string")})

        with (
            patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
            patch("conductor.cli.app.is_verbose", return_value=False),
            patch("conductor.cli.app.is_full", return_value=False),
        ):
            output = await provider.execute(agent, {}, "continue")

        assert output.session_id == "sess-actually-resumed-006"


class TestParseRecoveryLoopPreservesSessionId:
    """The trickiest of the three `_execute_sdk_call` reconstruction sites:
    `sdk_response` is captured once before the recovery loop and never
    reassigned across recovery attempts, even though `response_content` is
    overwritten each iteration. Confirms that invariant holds for
    `session_id` specifically, not just token counts."""

    @pytest.mark.asyncio
    async def test_session_id_survives_a_parse_recovery_round(self) -> None:
        session = FakeSession(response_content="not json the first time")
        session.session_id = "sess-recovers-007"

        # First send: unparseable. The recovery re-prompt (also routed
        # through FakeSession.send) then returns valid JSON.
        call_count = {"n": 0}
        original_send = session.send

        async def send_then_recover(data: Any) -> None:
            call_count["n"] += 1
            if call_count["n"] == 2:
                session._response_content = json.dumps({"val": "recovered"})
            await original_send(data)
            await asyncio.sleep(0.01)
            session._callback(FakeEvent("session.idle"))

        session.send = send_then_recover

        provider = CopilotProvider()
        provider._client = AsyncMock()
        provider._client.create_session = AsyncMock(return_value=session)
        provider._client.start = AsyncMock()
        provider._started = True

        agent = _make_agent("recovering", output={"val": OutputField(type="string")})

        with (
            patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
            patch("conductor.cli.app.is_verbose", return_value=False),
            patch("conductor.cli.app.is_full", return_value=False),
        ):
            output = await provider.execute(agent, {}, "do work")

        assert call_count["n"] >= 2, "the recovery path was never exercised"
        assert output.content == {"val": "recovered"}
        assert output.session_id == "sess-recovers-007"


class TestAwaitingModelEventCarriesSessionId:
    """The `agent_turn_start` / `{"turn": "awaiting_model"}` event fires right
    after `create_session`/`resume_session` returns, before the first prompt
    is even sent — the earliest point `session.session_id` is known. A step
    killed mid-turn (`conductor stop`, a crash) never reaches
    `session.idle`/`agent_completed`, so this is the earliest event on disk
    that can still name which session incurred whatever cost it ran up
    before dying, instead of that cost being unattributable after the fact."""

    @pytest.mark.asyncio
    async def test_awaiting_model_event_carries_session_id(self) -> None:
        provider = CopilotProvider(mock_handler=lambda a, p, c: {})
        session = FakeSession(response_content="normal response")
        session.session_id = "sess-awaiting-009"
        _deliver_idle_after_send(session)

        events: list[tuple[str, dict[str, Any]]] = []
        await provider._send_and_wait(
            session,
            "prompt",
            False,
            False,
            event_callback=lambda etype, data: events.append((etype, data)),
        )

        awaiting = [
            data
            for etype, data in events
            if etype == "agent_turn_start" and data.get("turn") == "awaiting_model"
        ]
        assert awaiting, "no 'awaiting_model' agent_turn_start event was emitted"
        assert awaiting[0]["session_id"] == "sess-awaiting-009"

    @pytest.mark.asyncio
    async def test_awaiting_model_event_session_id_none_when_session_has_no_id(self) -> None:
        """A session object with no `session_id` attribute at all must not
        raise — same getattr-default safety as the final read in
        _send_and_wait."""
        provider = CopilotProvider(mock_handler=lambda a, p, c: {})
        session = FakeSession(response_content="normal response")
        del session.session_id
        _deliver_idle_after_send(session)

        events: list[tuple[str, dict[str, Any]]] = []
        await provider._send_and_wait(
            session,
            "prompt",
            False,
            False,
            event_callback=lambda etype, data: events.append((etype, data)),
        )

        awaiting = [
            data
            for etype, data in events
            if etype == "agent_turn_start" and data.get("turn") == "awaiting_model"
        ]
        assert awaiting[0]["session_id"] is None


class TestSendFollowupCarriesSessionId:
    @pytest.mark.asyncio
    async def test_send_followup_reports_the_session_it_used(self) -> None:
        session = FakeSession(response_content=json.dumps({"result": "followup"}))
        session.session_id = "sess-followup-008"
        _deliver_idle_after_send(session)

        provider = CopilotProvider(mock_handler=lambda a, p, c: {})

        with (
            patch("conductor.cli.app.is_verbose", return_value=False),
            patch("conductor.cli.app.is_full", return_value=False),
        ):
            result = await provider.send_followup(session, "more guidance")

        assert result.session_id == "sess-followup-008"
