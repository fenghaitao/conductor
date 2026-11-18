"""Script execution for Conductor workflow steps."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from conductor.exceptions import ExecutionError
from conductor.execution import (
    CommandResult,
    CommandSpec,
    LocalRunnerBackend,
    RunnerBackend,
    WorkspaceLease,
)
from conductor.executor.template import TemplateRenderer


def _verbose_log(message: str, style: str = "dim") -> None:
    """Log a verbose message via the CLI run module."""
    from conductor.cli.run import verbose_log

    verbose_log(message, style)


if TYPE_CHECKING:
    from conductor.config.schema import AgentDef


@dataclass
class ScriptOutput:
    """Result of a script step execution."""

    stdout: str
    stderr: str
    exit_code: int


class ScriptExecutor:
    """Render a script step and delegate process execution to a runner backend."""

    def __init__(self, backend: RunnerBackend | None = None) -> None:
        self.renderer = TemplateRenderer()
        self._backend = backend or LocalRunnerBackend()
        if not self._backend.capabilities().batch:
            raise ExecutionError("Script execution backend does not support batch commands")

    async def execute(
        self,
        agent: AgentDef,
        context: dict[str, Any],
        *,
        lease: WorkspaceLease | None = None,
    ) -> ScriptOutput:
        assert agent.command is not None
        rendered_command = self.renderer.render(agent.command, context)
        rendered_args = [self.renderer.render(arg, context) for arg in agent.args]
        rendered_working_dir = (
            self.renderer.render(agent.working_dir, context) if agent.working_dir else None
        )

        result = await self._backend.run_command(
            CommandSpec(
                command=rendered_command,
                args=tuple(rendered_args),
                working_dir=rendered_working_dir,
                env=dict(agent.env),
                timeout=agent.timeout,
            ),
            lease,
            diagnostics=self._diagnostics(),
        )

        if result.outcome == "command_not_found":
            cause = self._reconstruct_start_error(result)
            hint = ""
            if sys.platform == "win32":
                hint = " Hint: on Windows, include the file extension or use an absolute path."
            raise ExecutionError(
                f"Script '{agent.name}': command not found: '{result.resolved_command}'"
                f" (working_dir={rendered_working_dir or 'cwd'}){hint}",
                agent_name=agent.name,
                suggestion=f"Ensure '{result.resolved_command}' is installed and in PATH",
            ) from cause

        if result.outcome == "start_failed":
            cause = self._reconstruct_start_error(result)
            raise ExecutionError(
                f"Script '{agent.name}' failed to start: {cause}",
                agent_name=agent.name,
            ) from cause

        if result.outcome == "timed_out":
            raise ExecutionError(
                f"Script '{agent.name}' timed out after {agent.timeout}s",
                agent_name=agent.name,
            )

        assert result.exit_code is not None
        return ScriptOutput(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
        )

    @staticmethod
    def _diagnostics() -> Callable[[str], None]:
        return _verbose_log

    @staticmethod
    def _reconstruct_start_error(result: CommandResult) -> OSError:
        start_error = result.start_error
        assert start_error is not None
        cause_type = FileNotFoundError if start_error.kind == "file_not_found" else OSError
        if start_error.errno is not None:
            return cause_type(start_error.errno, start_error.message, start_error.filename)
        return cause_type(start_error.message)
