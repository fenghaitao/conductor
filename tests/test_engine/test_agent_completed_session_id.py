"""Integration coverage: the Copilot session id reaches the workflow event
stream, not just the internal AgentOutput.

test_providers/test_copilot_session_id_output.py locks down that
`AgentOutput.session_id` is populated correctly at the provider layer. This
file is the other half of the claim: that `session_id` actually lands in the
`agent_completed`, `parallel_agent_completed`, and `for_each_item_completed`
event payloads a real workflow run emits — the thing an external consumer
(the JSONL event log, a dashboard, a script step reading a checkpoint) can
actually observe. A provider-level pass with no event-level check would leave
the exact wiring these tests exercise (`workflow.py`'s `_emit(...)` call
sites) unverified.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from conductor.config.schema import (
    AgentDef,
    ContextConfig,
    ForEachDef,
    LimitsConfig,
    OutputField,
    ParallelGroup,
    RouteDef,
    RuntimeConfig,
    WorkflowConfig,
    WorkflowDef,
)
from conductor.engine.workflow import WorkflowEngine
from conductor.events import WorkflowEvent, WorkflowEventEmitter
from conductor.providers.copilot import CopilotProvider
from tests.test_providers.test_copilot_interrupt import FakeEvent, FakeSession


class EventCollector:
    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def __call__(self, event: WorkflowEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: str) -> list[WorkflowEvent]:
        return [e for e in self.events if e.type == event_type]


def _emitter_and_collector() -> tuple[WorkflowEventEmitter, EventCollector]:
    emitter = WorkflowEventEmitter()
    collector = EventCollector()
    emitter.subscribe(collector)
    return emitter, collector


def _wire_idle(session: FakeSession) -> None:
    original_send = session.send

    async def send_with_idle(data: Any) -> None:
        await original_send(data)
        await asyncio.sleep(0.01)
        session._callback(FakeEvent("session.idle"))

    session.send = send_with_idle


def _fake_session_factory(prefix: str) -> tuple[AsyncMock, list[str]]:
    """A `create_session` side_effect that hands out one distinct FakeSession
    per call, each with its own session id — so a test can assert not just
    "some id was reported" but "each agent got ITS OWN session's id",
    catching a bug that stamped every completion with the same or the wrong
    session."""
    issued: list[str] = []

    async def _create(**kwargs: Any) -> FakeSession:
        sid = f"{prefix}-{len(issued)}"
        issued.append(sid)
        session = FakeSession(response_content='{"result": "ok"}')
        session.session_id = sid
        _wire_idle(session)
        return session

    return AsyncMock(side_effect=_create), issued


def _make_provider(prefix: str) -> tuple[CopilotProvider, list[str]]:
    create_session, issued = _fake_session_factory(prefix)
    provider = CopilotProvider()
    provider._client = AsyncMock()
    provider._client.create_session = create_session
    provider._client.start = AsyncMock()
    provider._started = True
    return provider, issued


@pytest.mark.asyncio
async def test_linear_agent_completed_carries_the_actual_session_id() -> None:
    emitter, collector = _emitter_and_collector()
    provider, issued = _make_provider("sess-linear")

    config = WorkflowConfig(
        workflow=WorkflowDef(
            name="linear",
            entry_point="a",
            runtime=RuntimeConfig(provider="copilot"),
            context=ContextConfig(mode="accumulate"),
            limits=LimitsConfig(max_iterations=10),
        ),
        agents=[
            AgentDef(
                name="a",
                model="gpt-4",
                prompt="do a",
                output={"result": OutputField(type="string")},
                routes=[RouteDef(to="$end")],
            ),
        ],
        output={"result": "done"},
    )
    engine = WorkflowEngine(config, provider, event_emitter=emitter)

    with (
        patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
        patch("conductor.cli.app.is_verbose", return_value=False),
        patch("conductor.cli.app.is_full", return_value=False),
    ):
        await engine.run({})

    completed = collector.of_type("agent_completed")
    assert len(completed) == 1
    assert completed[0].data["session_id"] == issued[0]
    assert completed[0].data["session_id"] is not None


@pytest.mark.asyncio
async def test_parallel_agent_completed_carries_each_agent_s_own_session_id() -> None:
    emitter, collector = _emitter_and_collector()
    provider, issued = _make_provider("sess-parallel")

    config = WorkflowConfig(
        workflow=WorkflowDef(
            name="parallel",
            entry_point="team",
            runtime=RuntimeConfig(provider="copilot"),
            context=ContextConfig(mode="accumulate"),
            limits=LimitsConfig(max_iterations=10),
        ),
        agents=[
            AgentDef(
                name="r1",
                model="gpt-4",
                prompt="research 1",
                output={"result": OutputField(type="string")},
            ),
            AgentDef(
                name="r2",
                model="gpt-4",
                prompt="research 2",
                output={"result": OutputField(type="string")},
            ),
        ],
        parallel=[
            ParallelGroup(name="team", agents=["r1", "r2"], routes=[RouteDef(to="$end")]),
        ],
        output={"result": "done"},
    )
    engine = WorkflowEngine(config, provider, event_emitter=emitter)

    with (
        patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
        patch("conductor.cli.app.is_verbose", return_value=False),
        patch("conductor.cli.app.is_full", return_value=False),
    ):
        await engine.run({})

    completed = collector.of_type("parallel_agent_completed")
    assert len(completed) == 2
    reported = {e.data["agent_name"]: e.data["session_id"] for e in completed}
    assert None not in reported.values()
    # Each agent's own session id, not one shared value copy-pasted across
    # both completions.
    assert len(set(reported.values())) == 2
    assert set(reported.values()) == set(issued)


@pytest.mark.asyncio
async def test_for_each_item_completed_carries_each_item_s_own_session_id() -> None:
    emitter, collector = _emitter_and_collector()
    provider, issued = _make_provider("sess-foreach")

    config = WorkflowConfig(
        workflow=WorkflowDef(
            name="foreach",
            entry_point="finder",
            runtime=RuntimeConfig(provider="copilot"),
            context=ContextConfig(mode="accumulate"),
            limits=LimitsConfig(max_iterations=20),
        ),
        agents=[
            AgentDef(
                name="finder",
                model="gpt-4",
                prompt="find items",
                output={"items": OutputField(type="array")},
                routes=[RouteDef(to="process_items")],
            ),
        ],
        for_each=[
            ForEachDef(
                name="process_items",
                type="for_each",
                source="finder.output.items",
                **{"as": "item"},
                agent=AgentDef(
                    name="processor",
                    model="gpt-4",
                    prompt="process {{ item }}",
                    output={"result": OutputField(type="string")},
                ),
                max_concurrent=1,
                routes=[RouteDef(to="$end")],
            ),
        ],
        output={"result": "done"},
    )
    engine = WorkflowEngine(config, provider, event_emitter=emitter)

    # `finder` also runs through the same fake provider, and its own
    # session-issuing call consumes the first entry in `issued` — its
    # completion isn't asserted on here, only for_each_item_completed is.
    with (
        patch("conductor.providers.copilot.CopilotProvider._log_event_verbose"),
        patch("conductor.cli.app.is_verbose", return_value=False),
        patch("conductor.cli.app.is_full", return_value=False),
    ):
        # finder must return real items for for_each to have anything to
        # iterate — patch its content via a session whose response encodes
        # the array, since the fake session factory always answers
        # {"result": "ok"}. Simplest: give finder its own dedicated session.
        async def _finder_session(**kwargs: Any) -> FakeSession:
            session = FakeSession(response_content='{"items": ["a", "b"]}')
            session.session_id = "sess-foreach-finder"
            _wire_idle(session)
            return session

        real_factory = provider._client.create_session
        calls = {"n": 0}

        async def _dispatch(**kwargs: Any) -> FakeSession:
            calls["n"] += 1
            if calls["n"] == 1:
                return await _finder_session(**kwargs)
            return await real_factory(**kwargs)

        provider._client.create_session = AsyncMock(side_effect=_dispatch)

        await engine.run({})

    completed = collector.of_type("for_each_item_completed")
    assert len(completed) == 2
    reported = [e.data["session_id"] for e in completed]
    assert None not in reported
    assert len(set(reported)) == 2, "each item must report its OWN session, not a shared one"
