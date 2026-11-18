from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from conductor.config.environment import (
    EnvironmentDocument,
    ProfileDefinition,
    ResolvedEnvironment,
    builtin_local_environment,
    resolve_environment,
)
from conductor.config.schema import (
    AgentDef,
    RouteDef,
    StepExecutionConfig,
    WorkflowConfig,
    WorkflowDef,
    WorkflowDefaults,
    WorkflowExecutionDefaults,
    WorkspaceConfig,
)
from conductor.engine.run_manifest import compile_run_manifest
from conductor.engine.workflow import WorkflowEngine
from conductor.exceptions import ConfigurationError


def _script_config(
    *,
    step_profile: str | None = None,
    workflow_profile: str | None = None,
    persistence: Literal["ephemeral", "durable", "on-failure"] = "ephemeral",
) -> WorkflowConfig:
    execution = StepExecutionConfig(profile=step_profile) if step_profile else None
    defaults = WorkflowDefaults(
        execution=WorkflowExecutionDefaults(profile=workflow_profile) if workflow_profile else None
    )
    return WorkflowConfig(
        workflow=WorkflowDef(
            name="profile-test",
            entry_point="run",
            defaults=defaults,
            workspace=WorkspaceConfig(persistence=persistence),
        ),
        agents=[
            AgentDef(
                name="run",
                type="script",
                command="echo",
                execution=execution,
                routes=[RouteDef(to="$end")],
            )
        ],
    )


def _environment(*, default: str = "shell") -> ResolvedEnvironment:
    document = EnvironmentDocument(
        default=default,
        profiles={
            "shell": ProfileDefinition(backend="local"),
            "isolated": ProfileDefinition(backend="local"),
        },
    )
    return ResolvedEnvironment(
        document=document,
        name="test",
        source="path",
        path=None,
        digest="sha256:test",
    )


def test_manifest_profile_precedence_and_workspace() -> None:
    config = _script_config(
        step_profile="isolated",
        workflow_profile="shell",
        persistence="on-failure",
    )
    manifest = compile_run_manifest(
        config,
        workflow_path=None,
        environment=_environment(),
    )

    assert manifest.profiles["run"].profile == "isolated"
    assert manifest.profiles["run"].backend == "local"
    assert manifest.workspace.persistence == "on-failure"
    assert manifest.workspace.mode == "shared"


def test_manifest_uses_workflow_default_then_environment_default() -> None:
    workflow_default = compile_run_manifest(
        _script_config(workflow_profile="isolated"),
        workflow_path=None,
        environment=_environment(),
    )
    assert workflow_default.profiles["run"].profile == "isolated"

    environment_default = compile_run_manifest(
        _script_config(),
        workflow_path=None,
        environment=_environment(),
    )
    assert environment_default.profiles["run"].profile == "shell"


def test_unknown_profile_fails_before_execution() -> None:
    with pytest.raises(ConfigurationError, match="missing"):
        compile_run_manifest(
            _script_config(step_profile="missing"),
            workflow_path=None,
            environment=_environment(),
        )


def test_project_environment_discovery(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow_dir = repo / "workflows"
    environment_dir = repo / ".conductor" / "environments"
    workflow_dir.mkdir(parents=True)
    environment_dir.mkdir(parents=True)
    (repo / ".git").mkdir()
    (environment_dir / "autodml.yaml").write_text(
        "default: vp\nprofiles:\n  vp:\n    backend: local\n",
        encoding="utf-8",
    )

    resolved = resolve_environment("autodml", workflow_dir=workflow_dir)

    assert resolved.source == "project"
    assert resolved.name == "autodml"
    assert resolved.document.default == "vp"


def test_workspace_isolated_is_reserved() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        WorkspaceConfig(mode="isolated")


def test_engine_publishes_manifest_in_workflow_started_system() -> None:
    engine = WorkflowEngine(
        _script_config(),
        workflow_path=None,
        execution_environment=builtin_local_environment(),
    )
    data = engine.build_workflow_started_data()

    manifest = data["system"]["execution_manifest"]
    assert manifest["environment"]["name"] == "local/default"
    assert manifest["profiles"]["run"]["backend"] == "local"
