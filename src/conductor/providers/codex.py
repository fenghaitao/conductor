"""Codex provider — drives a local Codex app-server via the ``openai-codex`` SDK.

The SDK controls a local Codex app-server over JSON-RPC. Unlike
:mod:`conductor.providers.openai`, which speaks Chat Completions through the
shared Pydantic AI runner, this provider delegates the whole agentic loop —
tool use, sandboxing, approvals — to Codex itself, in the same spirit as
:mod:`conductor.providers.claude_agent_sdk`.

Two structural facts about Codex shape everything here:

* **There is no tool allowlist.** ``thread_start`` takes no ``tools``
  parameter and neither does ``run``/``turn``. Access is scoped by
  ``Sandbox`` (read-only / workspace-write / full-access) and
  ``ApprovalMode``, not by an enumerated list. So
  ``workflow_tools_passthrough`` is ``False`` and a per-agent ``tools:``
  allowlist is refused rather than silently dropped.
* **Structured output is constrained, not guaranteed.** ``output_schema``
  is documented as constraining the final assistant message, but there is
  no strictness guarantee and no typed schema-violation error — a
  violation arrives as wrong-shaped *text*. ``final_response`` is a plain
  ``str``; nothing is pre-parsed for us (weaker than claude-agent-sdk,
  which hands back an already-parsed ``structured_output``). So the
  in-session recovery loop required by the parity rule is mandatory here,
  and the capability is declared ``prompt_injection`` to stay honest.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from conductor.exceptions import ProviderError, ValidationError
from conductor.executor.output import parse_json_output, validate_output
from conductor.install_hint import install_command
from conductor.providers._event_format import emit_parse_recovery_event
from conductor.providers._output_shape import normalize_agent_output
from conductor.providers._recovery_prompt import build_parse_recovery_prompt
from conductor.providers._schema import SchemaDepthError, build_json_schema_properties
from conductor.providers.base import AgentOutput, AgentProvider, EventCallback
from conductor.providers.capabilities import ProviderCapabilities
from conductor.providers.reasoning import ReasoningEffort, resolve_reasoning_effort

if TYPE_CHECKING:
    from conductor.config.schema import AgentDef, OutputField

try:
    from openai_codex import (  # ty: ignore[unresolved-import]
        ApprovalMode,
        AsyncCodex,
        CodexConfig,
        Sandbox,
        SkillInput,
        TextInput,
    )

    CODEX_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via the availability flag
    CODEX_SDK_AVAILABLE = False
    AsyncCodex: Any = None
    CodexConfig: Any = None
    Sandbox: Any = None
    ApprovalMode: Any = None
    SkillInput: Any = None
    TextInput: Any = None

logger = logging.getLogger(__name__)

_MAX_SCHEMA_DEPTH: Final[int] = 10
_MAX_PARSE_RECOVERY_ATTEMPTS: Final[int] = 2

_SESSION_ID_PREFIX: Final[str] = "codex:"
"""Namespace for thread ids in the checkpoint's flat ``copilot_session_ids``.

The engine merges every active provider's map into one field, and our keys
are agent names that genuinely collide with Copilot's — so ours are
prefixed, exactly as ``claude-agent-sdk`` namespaces its own.
"""

_DEFAULT_REASONING_EFFORT: Final[str] = "high"
"""Effort used when neither the agent nor the workflow names one.

Deliberately not Codex's own default. ``gpt-5.6-sol`` defaults to ``low``,
which suits an interactive session where a human reacts to a shallow answer;
a workflow step has no such reader, and its output is usually consumed by a
route or a downstream agent that cannot tell an under-reasoned answer from a
considered one.
"""

# Codex's ``ReasoningEffort`` enum names none/minimal/low/medium/high/xhigh,
# but it is deliberately OPEN: its ``_missing_`` hook mints a member for any
# non-empty string, and the app-server is the real authority on what a given
# model accepts. ``codex models()`` reports ``max`` (and an ``ultra`` that
# Conductor has no level for) among ``gpt-5.6-sol``'s supported efforts, so
# every Conductor level maps straight through.
#
# Support is per MODEL, not per provider: ``gpt-5.6-luna`` tops out at
# ``xhigh``. Conductor does not consult ``models()`` to check that pairing,
# so an unsupported effort surfaces as an app-server error rather than a
# validate-time one.
_EFFORT_MAP: Final[dict[str, str]] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}

# ThreadItem types that represent a tool the model invoked. Codex reports
# these as items rather than as a tool-call channel, so they are mapped onto
# Conductor's ``agent_tool_*`` pair to keep the dashboard, JSONL log and
# console subscriber consistent with every other provider.
_TOOL_ITEM_TYPES: Final[frozenset[str]] = frozenset(
    {
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "webSearch",
        "imageGeneration",
        "imageView",
        "dynamicToolCall",
        "collabAgentToolCall",
    }
)


def _describe_tool_item(kind: str, payload: Any) -> tuple[str, str, str]:
    """Render a tool item as ``(tool_name, arguments, result)``.

    Codex reports each tool as its own item *type* with its own field for
    "what was invoked" — a shell command, an MCP ``server``/``tool`` pair, a
    search query — so a single generic read would surface the item type and
    throw the useful half away. The names chosen here are the vocabulary a
    reader already knows (``shell``, ``apply_patch``, ``web_search``) rather
    than the wire discriminators.

    ``tool_name`` is the key every other provider emits and the one the
    console subscriber and dashboard read; sending ``tool`` instead renders
    as "unknown".
    """
    status = str(getattr(payload, "status", "") or "")
    if kind == "commandExecution":
        return (
            "shell",
            str(getattr(payload, "command", "") or ""),
            str(getattr(payload, "aggregated_output", None) or status),
        )
    if kind == "mcpToolCall":
        server = str(getattr(payload, "server", "") or "")
        tool = str(getattr(payload, "tool", "") or kind)
        error = getattr(payload, "error", None)
        return (
            f"{server}/{tool}" if server else tool,
            str(getattr(payload, "arguments", "") or ""),
            str(getattr(error, "message", None) or status),
        )
    if kind == "fileChange":
        changes = getattr(payload, "changes", None) or []
        return ("apply_patch", f"{len(changes)} file(s)", status)
    if kind == "webSearch":
        return ("web_search", str(getattr(payload, "query", "") or ""), status)
    return (kind, "", status)


@dataclass(slots=True)
class _TurnOutcome:
    """What one Codex turn produced, collected from its notification stream."""

    final_response: str | None
    status: str
    error: Any
    usage: Any
    interrupted: bool


def _final_response_from_items(items: list[Any]) -> str | None:
    """Pick the turn's final assistant message.

    Mirrors the SDK's own rule: a message explicitly phased as the final
    answer wins outright; otherwise the last phase-less message stands. Codex
    emits intermediate assistant messages during a turn, so taking simply the
    last one would return a progress note instead of the answer.
    """
    fallback: str | None = None
    for item in reversed(items):
        payload = _item_payload(item)
        if _item_type(item) != "agentMessage":
            continue
        phase = getattr(payload, "phase", None)
        phase_name = getattr(phase, "value", phase)
        if phase_name == "finalAnswer" or phase_name == "final_answer":
            return getattr(payload, "text", None)
        if phase is None and fallback is None:
            fallback = getattr(payload, "text", None)
    return fallback


def _item_type(item: Any) -> str:
    """Return a ThreadItem's discriminator, unwrapping a pydantic root model."""
    inner = getattr(item, "root", item)
    return str(getattr(inner, "type", "") or "")


def _item_payload(item: Any) -> Any:
    """Unwrap a ThreadItem to the concrete model carrying its fields."""
    return getattr(item, "root", item)


class CodexProvider(AgentProvider):
    """Runs agents through a local Codex app-server."""

    CAPABILITIES = ProviderCapabilities(
        tier="experimental",
        # Codex speaks MCP, but Conductor does not translate
        # ``runtime.mcp_servers`` into its config shape -- a workflow's
        # declared servers are NOT forwarded. This flag means "the configured
        # set is forwarded" (``aca`` declares ``True`` because its runner
        # attaches every one), so ``True`` here would be a lie. Servers reach
        # Codex only through Codex's own configuration.
        mcp_tools=False,
        # There is no tool allowlist surface to pass one through to. See the
        # module docstring: access is sandbox-scoped, not enumerated.
        workflow_tools_passthrough=False,
        # Turn notifications arrive incrementally over the JSON-RPC stream.
        streaming_events=True,
        # ``reasoning`` items and the ReasoningTextDelta notifications are
        # forwarded as ``agent_reasoning``.
        agent_reasoning_events=True,
        # All five Conductor levels reach Codex. The SDK enum's names stop at
        # ``xhigh``, but the enum is open and ``models()`` advertises ``max``
        # for the default model — see ``_EFFORT_MAP``.
        reasoning_effort=("low", "medium", "high", "xhigh", "max"),
        # ``output_schema`` constrains the final message but carries no
        # strictness guarantee and no typed violation error, and the result
        # arrives as an unparsed string. Follow-on parsing plus the recovery
        # loop is what actually enforces the schema -- so declare the honest
        # weaker value, matching the identical call ``claude-agent-sdk``
        # makes about its own native ``output_format``.
        structured_output="prompt_injection",
        # ``AsyncTurnHandle.interrupt()`` cancels the in-flight turn.
        interrupt=True,
        # No native wall-clock cap; enforced here between stream events.
        max_session_seconds=True,
        # Threads persist server-side and ``thread_resume`` reattaches to one,
        # so a checkpointed thread id genuinely continues its conversation.
        checkpoint_resume=True,
        usage_tracking=True,
        # Each execution owns its own thread; the id map is a plain dict
        # mutated only from the event loop.
        concurrent_safe=True,
        # ``cwd`` is accepted on both thread lifecycle methods and turns.
        working_dir=True,
        # Skills are native but differently shaped from every other provider:
        # Codex takes ``SkillInput(name, path)`` items inline with the turn
        # input rather than a session-level directory list.
        skills=True,
        # No host-plugin surface, and there is no eager-injection fallback
        # that could produce a subagent or an MCP server from prompt text.
        plugins=False,
        session_continuity=True,
        # Codex exposes no temperature parameter; sampling is model-side.
        max_temperature=None,
        upstream_pin="openai-codex>=0.147.0",
        maintainer="unassigned (experimental)",
    )

    def __init__(
        self,
        model: str | None = None,
        max_session_seconds: float | None = None,
        sandbox: str | None = None,
        approval_mode: str | None = None,
        default_reasoning_effort: ReasoningEffort | None = None,
        **_ignored: Any,
    ) -> None:
        """Construct the provider.

        Args:
            model: Default model for every agent that does not name one.
            max_session_seconds: Wall-clock cap enforced between stream
                events.
            sandbox: Codex sandbox preset (``read-only`` /
                ``workspace-write`` / ``full-access``). Defaults to Codex's
                own configured default when omitted.
            approval_mode: ``deny_all`` or ``auto_review``. Defaults to
                ``deny_all`` -- an unattended workflow has nobody to answer
                an approval prompt, so requesting review would hang.
            default_reasoning_effort: Workflow-wide ``reasoning.effort``
                default, from ``runtime.default_reasoning_effort``. Falls
                back to :data:`_DEFAULT_REASONING_EFFORT`.
            **_ignored: Runtime fields other providers accept that Codex has
                no equivalent for (e.g. ``temperature``). Swallowed so the
                factory can pass a uniform kwarg set.

        Raises:
            ProviderError: If the ``openai-codex`` package is not installed
                or a preset name is not recognised.
        """
        if not CODEX_SDK_AVAILABLE:
            raise ProviderError(
                "The 'openai-codex' package is required for the codex provider "
                "but is not installed.",
                suggestion=f"Install it with: {install_command('codex')}",
            )

        self._model = model
        self._max_session_seconds = max_session_seconds
        self._default_reasoning_effort = default_reasoning_effort
        self._sandbox = self._coerce_sandbox(sandbox)
        self._approval_mode = self._coerce_approval_mode(approval_mode)

        self._client: Any = None
        self._start_lock = asyncio.Lock()
        # session_key -> Codex thread id, for cross-execution continuity.
        self._thread_ids: dict[str, str] = {}
        self._restored_thread_ids: dict[str, str] = {}

    @staticmethod
    def _coerce_sandbox(value: str | None) -> Any:
        """Map a configured sandbox name onto the SDK enum."""
        if value is None:
            return None
        try:
            return Sandbox(value)  # ty: ignore[call-non-callable]
        except ValueError as exc:
            allowed = ", ".join(preset.value for preset in Sandbox)  # ty: ignore[not-iterable]
            raise ProviderError(
                f"Unknown Codex sandbox preset {value!r}.",
                suggestion=f"Use one of: {allowed}.",
            ) from exc

    @staticmethod
    def _coerce_approval_mode(value: str | None) -> Any:
        """Map a configured approval mode onto the SDK enum.

        Defaults to ``deny_all``. A Conductor run is unattended, so
        ``auto_review`` -- the SDK's own default -- would route an escalation
        to a reviewer who is not there and stall the turn.
        """
        if value is None:
            return ApprovalMode.deny_all  # ty: ignore[possibly-missing-attribute]
        try:
            return ApprovalMode(value)  # ty: ignore[call-non-callable]
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in ApprovalMode)  # ty: ignore[not-iterable]
            raise ProviderError(
                f"Unknown Codex approval mode {value!r}.",
                suggestion=f"Use one of: {allowed}.",
            ) from exc

    @staticmethod
    def _resolve_cwd(agent: AgentDef) -> str | None:
        """Return the working directory for this agent's thread.

        ``agent.working_dir`` has already been rendered, absolutised and
        existence-checked by ``WorkflowEngine._resolve_agent_working_dir``, so
        it is passed verbatim -- re-resolving here would collapse the symlink
        aliases the engine preserves on purpose. ``None`` lets Codex use its
        own default rather than pinning the process cwd, which may not be the
        project the workflow is about.
        """
        return getattr(agent, "working_dir", None)

    @property
    def supports_native_skills(self) -> bool:
        """Codex loads skills itself, from ``SkillInput`` items on the turn."""
        return True

    async def _ensure_client(self) -> Any:
        """Start the app-server connection once, under a lock."""
        if self._client is not None:
            return self._client
        async with self._start_lock:
            if self._client is not None:
                return self._client
            client = AsyncCodex(CodexConfig())  # ty: ignore[call-non-callable]
            try:
                # ``AsyncCodex`` initializes lazily and exposes no ``start()``;
                # the SDK documents context entry as the standard path because
                # it pairs startup with shutdown. We drive ``__aenter__``
                # directly since the client's lifetime spans many ``execute``
                # calls and cannot sit inside a single ``async with``.
                await client.__aenter__()
            except Exception as exc:
                raise ProviderError(
                    f"Could not start the Codex app-server: {exc}",
                    suggestion=(
                        "Check that the bundled `codex` binary is runnable and "
                        "that you are signed in (`codex login`)."
                    ),
                ) from exc
            self._client = client
            return client

    async def validate_connection(self) -> bool:
        """Confirm the app-server starts and an account is available."""
        try:
            client = await self._ensure_client()
            await client.account()
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Codex connection check failed: {exc}",
                suggestion="Run `codex login` to authenticate, then retry.",
            ) from exc
        return True

    async def close(self) -> None:
        """Shut the app-server connection down."""
        if self._client is None:
            return
        client, self._client = self._client, None
        try:
            await client.close()
        except Exception:  # pragma: no cover - shutdown is best-effort
            logger.debug("Codex client close failed", exc_info=True)

    def get_session_ids(self) -> dict[str, str]:
        """Return checkpointable thread ids, namespaced by provider.

        Duck-typed hook the engine calls when writing a checkpoint, mirroring
        the Copilot and claude-agent-sdk hooks of the same name. Restored ids
        are re-exported alongside ones recorded this run so a checkpoint taken
        before a keyed agent runs again does not drop them.
        """
        merged = {**self._restored_thread_ids, **self._thread_ids}
        return {f"{_SESSION_ID_PREFIX}{key}": value for key, value in merged.items()}

    def set_resume_session_ids(self, session_ids: dict[str, str]) -> None:
        """Restore thread ids from a checkpoint, ignoring other providers' keys."""
        for raw_key, value in (session_ids or {}).items():
            if not raw_key.startswith(_SESSION_ID_PREFIX):
                continue
            self._restored_thread_ids[raw_key[len(_SESSION_ID_PREFIX) :]] = value

    def _build_output_schema(self, output: dict[str, OutputField]) -> dict[str, Any]:
        """Build the JSON Schema document passed as ``output_schema``.

        Codex takes a bare JSON Schema, unlike the claude-agent-sdk which
        wants it wrapped in ``{"type": "json_schema", "schema": ...}``.
        """
        try:
            properties = build_json_schema_properties(output, depth=0, max_depth=_MAX_SCHEMA_DEPTH)
        except SchemaDepthError as exc:
            raise ProviderError(
                f"Output schema nesting exceeds {_MAX_SCHEMA_DEPTH} levels"
            ) from exc
        return {
            "type": "object",
            "properties": properties,
            "required": list(output.keys()),
            "additionalProperties": False,
        }

    def _resolve_effort(self, agent: AgentDef) -> str | None:
        """Translate Conductor's reasoning effort to Codex's enum value.

        Precedence is per-agent ``reasoning.effort``, then the workflow's
        ``runtime.default_reasoning_effort``, then this provider's own
        :data:`_DEFAULT_REASONING_EFFORT`. The last rung is why this returns
        a value where the other providers return ``None``: sending nothing
        lets Codex apply the *model's* default, which is ``low`` on
        ``gpt-5.6-sol`` and too shallow for the multi-step work a workflow
        step usually is.

        Raises:
            ValidationError: If the effort is not one Conductor defines.
                Checked here as well as statically because ``conductor run``
                never calls the cross-reference validator, and because an
                effort that only resolves after Jinja rendering is invisible
                until now.
        """
        effort = resolve_reasoning_effort(agent, self._default_reasoning_effort)
        if effort is None:
            effort = _DEFAULT_REASONING_EFFORT
        mapped = _EFFORT_MAP.get(str(effort))
        if mapped is None:
            raise ValidationError(
                f"Agent '{agent.name}' requests reasoning effort {effort!r}, "
                "which the codex provider does not recognise.",
                suggestion=(
                    "Use one of: low, medium, high, xhigh, max. Not every "
                    "model accepts every level — `codex models` lists the "
                    "efforts each one supports."
                ),
            )
        return mapped

    def _reject_tool_allowlist(self, tools: list[str] | None, agent: AgentDef) -> None:
        """Refuse a per-agent ``tools:`` allowlist.

        The ``tools`` argument is the executor's *resolved* list, which erases
        the omitted-vs-explicit distinction whenever the workflow declares no
        workflow-level tools. We therefore consult the raw ``agent.tools``
        field -- the same approach ``claude_agent_sdk._resolve_tool_config``
        takes, and the reason porting the executor-side fix is unnecessary
        here.

        Codex has no allowlist surface at all, so unlike claude-agent-sdk
        there is no meaningful ``tools: []`` either: every turn runs with the
        sandbox's tools, and the nearest expression of "none" is
        ``Sandbox.read_only``, which is a different promise and would be a lie
        to present as equivalent.

        Known gap: ``config/validator.py`` only refuses ``tools: []`` for a
        non-passthrough provider when ``mcp_tools`` is set *and* the workflow
        declares ``mcp_servers`` -- neither holds for Codex -- so a workflow
        using ``tools: []`` passes ``conductor validate`` and is refused here
        instead. Closing that needs a validator branch for "cannot honor an
        empty allowlist either", which is a capability distinction the
        descriptor does not currently draw.
        """
        if agent.tools is None:
            return
        raise ProviderError(
            f"Agent '{agent.name}' declares tools={agent.tools!r}, but the codex "
            "provider has no tool allowlist to apply it to -- Codex scopes tool "
            "access by sandbox, not by an enumerated list.",
            suggestion=(
                "Remove the 'tools:' field and restrict the agent with the "
                "provider's `sandbox` setting (read-only / workspace-write / "
                "full-access) instead."
            ),
        )

    def _build_turn_input(self, prompt: str, skill_directories: list[str] | None) -> Any:
        """Assemble the turn input, attaching skills as ``SkillInput`` items.

        Codex takes skills as ``(name, path)`` pairs inline with the prompt
        rather than as a session-level directory list, so they are rebuilt on
        every turn.
        """
        from pathlib import Path

        items: list[Any] = [TextInput(text=prompt)]  # ty: ignore[call-non-callable]
        for directory in skill_directories or []:
            items.append(SkillInput(name=Path(directory).name, path=str(directory)))  # ty: ignore[call-non-callable]
        return items

    def _emit_item_events(self, item: Any, event_callback: EventCallback | None) -> None:
        """Forward a completed ThreadItem as the matching Conductor event."""
        if event_callback is None:
            return
        kind = _item_type(item)
        payload = _item_payload(item)
        if kind == "agentMessage":
            text = getattr(payload, "text", "")
            if text:
                self._safe_emit(event_callback, "agent_message", {"content": text})
        elif kind == "reasoning":
            text = getattr(payload, "text", None) or getattr(payload, "summary", "")
            if text:
                self._safe_emit(event_callback, "agent_reasoning", {"content": str(text)})
        elif kind in _TOOL_ITEM_TYPES:
            name, arguments, result = _describe_tool_item(kind, payload)
            self._safe_emit(
                event_callback,
                "agent_tool_start",
                {"tool_name": name, "arguments": arguments},
            )
            self._safe_emit(
                event_callback,
                "agent_tool_complete",
                {"tool_name": name, "result": result},
            )

    @staticmethod
    def _safe_emit(event_callback: EventCallback, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event, swallowing subscriber errors.

        A dashboard subscriber raising must not abort the agent's turn.
        """
        try:
            event_callback(event_type, data)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Codex event subscriber failed for %s", event_type, exc_info=True)

    async def _run_turn(
        self,
        thread: Any,
        turn_input: Any,
        *,
        output_schema: dict[str, Any] | None,
        effort: str | None,
        model: str | None,
        interrupt_signal: asyncio.Event | None,
        event_callback: EventCallback | None,
        cwd: str | None = None,
    ) -> _TurnOutcome:
        """Start one turn, then stream and collect it in a **single** pass.

        The stream is consumed exactly once. ``AsyncTurnHandle.run()`` is
        deliberately not called afterwards: it opens ``stream()`` again, and a
        turn's notifications are delivered once, so draining the stream here
        and then awaiting ``run()`` waits forever for events that have already
        been consumed. Collection therefore mirrors the SDK's own
        ``_collect_async_turn_result`` rather than delegating to it -- that
        helper is private, and reaching into it would couple us to an
        underscore-prefixed symbol for the sake of a dozen lines.
        """
        kwargs: dict[str, Any] = {}
        if output_schema is not None:
            kwargs["output_schema"] = output_schema
        if effort is not None:
            kwargs["effort"] = effort
        if model is not None:
            kwargs["model"] = model
        if self._sandbox is not None:
            kwargs["sandbox"] = self._sandbox
        if cwd is not None:
            kwargs["cwd"] = cwd

        handle = await thread.turn(turn_input, **kwargs)
        turn_id = getattr(handle, "id", None)

        if event_callback is not None:
            self._safe_emit(event_callback, "agent_turn_start", {"turn": "awaiting_model"})

        loop = asyncio.get_running_loop()
        deadline = (
            loop.time() + self._max_session_seconds
            if self._max_session_seconds is not None
            else None
        )

        items: list[Any] = []
        usage: Any = None
        completed: Any = None
        interrupted = False

        try:
            async for notification in handle.stream():
                payload = getattr(notification, "payload", notification)
                name = type(payload).__name__
                if name == "ItemCompletedNotification" and self._for_turn(payload, turn_id):
                    items.append(getattr(payload, "item", None))
                elif name == "ThreadTokenUsageUpdatedNotification" and self._for_turn(
                    payload, turn_id
                ):
                    usage = getattr(payload, "token_usage", None)
                elif name == "TurnCompletedNotification":
                    completed = getattr(payload, "turn", None)

                self._dispatch_notification(notification, event_callback)

                # Checked *after* collecting the notification, not before: an
                # interrupt should keep the text that already arrived rather
                # than discard the message it raced. This is the same
                # "between messages" granularity claude-agent-sdk offers.
                if interrupt_signal is not None and interrupt_signal.is_set():
                    await self._interrupt(handle)
                    interrupted = True
                    break
                if deadline is not None and loop.time() > deadline:
                    await self._interrupt(handle)
                    raise ProviderError(
                        "Codex turn exceeded max_session_seconds "
                        f"({self._max_session_seconds}s) and was interrupted."
                    )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Codex turn failed: {exc}") from exc

        status = str(getattr(completed, "status", "") or "")
        return _TurnOutcome(
            final_response=_final_response_from_items(items),
            status=status,
            error=getattr(completed, "error", None),
            usage=usage,
            interrupted=interrupted or status.endswith("interrupted"),
        )

    @staticmethod
    def _for_turn(payload: Any, turn_id: str | None) -> bool:
        """Whether a notification belongs to the turn we started.

        One client can stream several turns concurrently, so an unfiltered
        read would fold a sibling for-each branch's items into this result.
        A handle that reports no id degrades to accepting everything, which
        is what the single-turn case already is.
        """
        if turn_id is None:
            return True
        return getattr(payload, "turn_id", turn_id) == turn_id

    @staticmethod
    async def _interrupt(handle: Any) -> None:
        """Interrupt an in-flight turn, best effort."""
        try:
            await handle.interrupt()
        except Exception:  # pragma: no cover - interrupt is best-effort
            logger.debug("Codex turn interrupt failed", exc_info=True)

    def _dispatch_notification(
        self, notification: Any, event_callback: EventCallback | None
    ) -> None:
        """Map one streamed notification onto Conductor's event vocabulary."""
        if event_callback is None:
            return
        payload = getattr(notification, "payload", notification)
        name = type(payload).__name__

        if name == "TurnStartedNotification":
            self._safe_emit(event_callback, "agent_turn_start", {"turn": 1})
        elif name == "AgentMessageDeltaNotification":
            delta = getattr(payload, "delta", "") or ""
            if delta:
                self._safe_emit(event_callback, "agent_message", {"content": delta})
        elif name in ("ReasoningTextDeltaNotification", "ReasoningSummaryTextDeltaNotification"):
            delta = getattr(payload, "delta", "") or ""
            if delta:
                self._safe_emit(event_callback, "agent_reasoning", {"content": delta})
        elif name == "ItemCompletedNotification":
            self._emit_item_events(getattr(payload, "item", None), event_callback)

    async def execute(
        self,
        agent: AgentDef,
        context: dict[str, Any],
        rendered_prompt: str,
        tools: list[str] | None = None,
        interrupt_signal: asyncio.Event | None = None,
        event_callback: EventCallback | None = None,
        skill_directories: list[str] | None = None,
        custom_agents: list[dict[str, Any]] | None = None,
        extra_mcp_servers: dict[str, Any] | None = None,
    ) -> AgentOutput:
        """Execute one agent as a Codex turn.

        Raises:
            ProviderError: On a declared ``tools:`` allowlist, a failed turn,
                or a response that stays unparseable after the recovery
                budget is spent.
            ValidationError: On an unsupported reasoning effort, or a response
                that parses but does not match the declared schema after
                recovery.
        """
        self._reject_tool_allowlist(tools, agent)
        if custom_agents or extra_mcp_servers:
            raise ProviderError(
                f"Agent '{agent.name}' declares plugins, which the codex provider "
                "does not support.",
                suggestion="Remove 'plugins:' for this agent, or use the copilot provider.",
            )

        # Resolve everything that can fail on configuration alone *before*
        # starting the app-server: a rejected reasoning effort or an
        # over-deep schema is a workflow error, and paying for a process
        # spawn to report it just makes the failure slower.
        effort = self._resolve_effort(agent)
        model = getattr(agent, "model", None) or self._model
        output_schema = self._build_output_schema(agent.output) if agent.output else None

        client = await self._ensure_client()

        thread = await self._open_thread(client, agent, model)
        turn_input = self._build_turn_input(rendered_prompt, skill_directories)

        result = await self._run_turn(
            thread,
            turn_input,
            output_schema=output_schema,
            effort=effort,
            model=model,
            interrupt_signal=interrupt_signal,
            event_callback=event_callback,
            cwd=self._resolve_cwd(agent),
        )

        self._record_thread_id(agent, thread)
        interrupted = result.interrupted

        if result.status.endswith("failed"):
            message = getattr(result.error, "message", None) or "Codex turn failed."
            raise ProviderError(f"Agent '{agent.name}': {message}")

        content = await self._resolve_content(
            result,
            thread,
            agent,
            output_schema=output_schema,
            effort=effort,
            model=model,
            event_callback=event_callback,
            partial=interrupted,
        )

        # ``ThreadTokenUsage`` nests two breakdowns: ``total`` for the whole
        # thread and ``last`` for the most recent call. They map onto the two
        # distinct figures ``AgentOutput`` wants -- billing totals versus the
        # single-call prompt size the context-window bar reads (issue #412) --
        # so reading flat token attributes off the wrapper yields ``None``.
        usage = result.usage
        total = getattr(usage, "total", None)
        last = getattr(usage, "last", None)
        return AgentOutput(
            content=content,
            raw_response=result.final_response,
            input_tokens=getattr(total, "input_tokens", None),
            output_tokens=getattr(total, "output_tokens", None),
            tokens_used=getattr(total, "total_tokens", None),
            cache_read_tokens=getattr(total, "cached_input_tokens", 0) or 0,
            cache_write_tokens=getattr(total, "cache_write_input_tokens", 0) or 0,
            last_call_input_tokens=getattr(last, "input_tokens", None),
            model=model,
            partial=interrupted,
        )

    async def _open_thread(self, client: Any, agent: AgentDef, model: str | None) -> Any:
        """Start a new thread, or resume the one this ``session_key`` owns."""
        kwargs: dict[str, Any] = {"approval_mode": self._approval_mode}
        if model is not None:
            kwargs["model"] = model
        if self._sandbox is not None:
            kwargs["sandbox"] = self._sandbox
        cwd = self._resolve_cwd(agent)
        if cwd is not None:
            kwargs["cwd"] = cwd
        if agent.system_prompt:
            kwargs["developer_instructions"] = agent.system_prompt

        key = getattr(agent, "session_key", None)
        if key:
            existing = self._thread_ids.get(key) or self._restored_thread_ids.get(key)
            if existing:
                try:
                    return await client.thread_resume(existing, **kwargs)
                except Exception:
                    # A pruned or unreachable thread must not fail the run --
                    # start fresh, exactly as claude-agent-sdk degrades when
                    # its transcript guard finds no transcript.
                    logger.debug(
                        "Codex thread %s could not be resumed; starting fresh",
                        existing,
                        exc_info=True,
                    )
        return await client.thread_start(**kwargs)

    def _record_thread_id(self, agent: AgentDef, thread: Any) -> None:
        """Remember this thread id if the agent declared a ``session_key``."""
        key = getattr(agent, "session_key", None)
        thread_id = getattr(thread, "id", None)
        if key and thread_id:
            self._thread_ids[key] = str(thread_id)

    async def _resolve_content(
        self,
        result: Any,
        thread: Any,
        agent: AgentDef,
        *,
        output_schema: dict[str, Any] | None,
        effort: str | None,
        model: str | None,
        event_callback: EventCallback | None,
        partial: bool,
    ) -> dict[str, Any]:
        """Parse and validate the final response, re-prompting on failure.

        Codex returns a string even when ``output_schema`` is set, and a
        schema violation is not reported as a typed error -- so parsing and
        validation happen here, and a failure is corrected in-session by
        running a further turn on the same thread. ``steer()`` is deliberately
        not used: it requires an *active* turn, and by this point the turn has
        completed.
        """
        raw = result.final_response or ""

        if not agent.output:
            return {"response": raw}

        attempt = 0
        current = raw
        last_error: Exception | None = None

        while attempt <= _MAX_PARSE_RECOVERY_ATTEMPTS:
            try:
                parsed = parse_json_output(current)
                normalized = normalize_agent_output(parsed, agent.output)
                validate_output(normalized, agent.output)
                return normalized
            except ValidationError as exc:
                last_error = exc
                is_schema_failure = not isinstance(
                    getattr(exc, "__cause__", None), json.JSONDecodeError
                )
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc
                is_schema_failure = False

            if partial:
                # An interrupted turn is best-effort by definition; surface
                # what arrived rather than burning the recovery budget.
                return {"response": current}

            attempt += 1
            if attempt > _MAX_PARSE_RECOVERY_ATTEMPTS:
                break

            emit_parse_recovery_event(
                event_callback,
                attempt=attempt,
                max_attempts=_MAX_PARSE_RECOVERY_ATTEMPTS,
                is_schema_failure=is_schema_failure,
                error=str(last_error),
            )
            recovery_prompt = build_parse_recovery_prompt(
                str(last_error),
                current,
                output_schema or {},
                is_schema_failure=is_schema_failure,
            )
            retry = await self._run_turn(
                thread,
                recovery_prompt,
                output_schema=output_schema,
                effort=effort,
                model=model,
                interrupt_signal=None,
                event_callback=event_callback,
                cwd=self._resolve_cwd(agent),
            )
            current = retry.final_response or ""

        # Budget spent. Re-raise the original ValidationError where we have
        # one -- it names the field and the expected type, which a generic
        # ProviderError would throw away.
        if isinstance(last_error, ValidationError):
            raise last_error
        raise ProviderError(
            f"Agent '{agent.name}' returned a response that could not be parsed "
            f"as JSON after {_MAX_PARSE_RECOVERY_ATTEMPTS} recovery attempts: "
            f"{last_error}",
            suggestion="Simplify the output schema, or check the model's instructions.",
        )
