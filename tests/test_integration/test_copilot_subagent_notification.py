"""Real-Copilot check for notification-driven subagent continuation.

Run with:
    pytest -m real_api tests/test_integration/test_copilot_subagent_notification.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conductor.config.schema import (
    AgentDef,
    OutputField,
    RouteDef,
    RuntimeConfig,
    WorkflowConfig,
    WorkflowDef,
)
from conductor.engine.workflow import WorkflowEngine
from conductor.providers.copilot import CopilotProvider


def _has_copilot_cli() -> bool:
    return shutil.which("copilot") is not None


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


@pytest.mark.real_api
@pytest.mark.asyncio
async def test_subagent_completion_resumes_without_read_agent() -> None:
    """A background subagent completion must resume its yielded parent."""
    if not _has_copilot_cli():
        pytest.skip("Copilot CLI not available — skipping real-API test")

    prompt = """
Run this notification probe exactly:
1. Use the task tool to start one background general-purpose subagent. Tell it
   to run `sleep 2`, then return exactly `NOTIFICATION_PROBE_OK`.
2. Never call `read_agent`, including for status or result retrieval.
3. After dispatch, end the current turn and wait for Copilot CLI's completion
   notification. Do not continue early and do not poll.
4. Only after the notification, return JSON with state `passed` and
   child_result `NOTIFICATION_PROBE_OK`.
"""
    workflow = WorkflowConfig(
        workflow=WorkflowDef(
            name="copilot-subagent-notification",
            entry_point="notification_probe",
            runtime=RuntimeConfig(provider="copilot"),
        ),
        agents=[
            AgentDef(
                name="notification_probe",
                model="claude-sonnet-5",
                prompt=prompt,
                output={
                    "state": OutputField(type="string"),
                    "child_result": OutputField(type="string"),
                },
                routes=[RouteDef(to="$end")],
                max_session_seconds=120.0,
            )
        ],
        output={
            "state": "{{ notification_probe.output.state }}",
            "child_result": "{{ notification_probe.output.child_result }}",
        },
    )

    provider = CopilotProvider()
    try:
        result = await WorkflowEngine(workflow, provider).run({})
        session_id = provider.get_session_ids()["notification_probe"]
    finally:
        await provider.close()

    assert result["state"] == "passed"
    assert result["child_result"] == "NOTIFICATION_PROBE_OK"

    events_path = Path.home() / ".copilot" / "session-state" / session_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]

    tool_starts = [
        _event_data(event)
        for event in events
        if event.get("type") == "tool.execution_start"
    ]
    assert all(data.get("toolName") != "read_agent" for data in tool_starts)

    started_at = next(
        index for index, event in enumerate(events) if event.get("type") == "subagent.started"
    )
    task_call_id = _event_data(events[started_at])["toolCallId"]
    launch_returned_at = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "tool.execution_complete"
        and _event_data(event).get("toolCallId") == task_call_id
    )
    completed_at = next(
        index for index, event in enumerate(events) if event.get("type") == "subagent.completed"
    )
    assert launch_returned_at < completed_at, "task tool did not return while the child was running"
    assert any(
        event.get("type") == "assistant.turn_end"
        for event in events[launch_returned_at + 1 : completed_at]
    ), "parent did not yield after dispatching the background child"
    assert any(
        event.get("type") == "assistant.message"
        and not event.get("agentId")
        and "NOTIFICATION_PROBE_OK" in str(_event_data(event).get("content", ""))
        for event in events[completed_at + 1 :]
    ), "parent did not produce its final result after the subagent completion notification"
