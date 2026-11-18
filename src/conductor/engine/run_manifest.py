"""Deterministic execution manifest for profile-resolved workflow runs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from conductor.config.environment import ResolvedEnvironment
from conductor.config.schema import AgentDef, WorkflowConfig
from conductor.exceptions import ConfigurationError


class WorkflowIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    digest: str | None


class EnvironmentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    source: Literal["builtin", "path", "project", "user"]
    digest: str


class ResolvedStepProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: str
    backend: str


class WorkspaceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["shared"]
    persistence: Literal["ephemeral", "durable", "on-failure"]


class ResolvedRunManifest(BaseModel):
    """Run-invariant audit record of execution resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    workflow: WorkflowIdentity
    environment: EnvironmentIdentity
    profiles: dict[str, ResolvedStepProfile]
    workspace: WorkspaceIdentity
    hermetic: Literal[False] = False


def executable_step_identity(name: str, *, for_each_group: str | None = None) -> str:
    if for_each_group is not None:
        return f"for_each.{for_each_group}.agent"
    return name


def _workflow_digest(path: Path | str | None) -> str | None:
    if path is None or not isinstance(path, Path):
        # WorkflowEngine historically accepted synthetic string identifiers in
        # programmatic/test construction even though the public annotation is
        # Path | None. Preserve that compatibility: only a concrete Path
        # represents file bytes that the manifest can truthfully hash.
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(
            f"Failed to hash workflow file '{path}': {exc}",
            file_path=str(path),
        ) from exc
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _is_executable(step: AgentDef) -> bool:
    return step.type in (None, "agent", "script", "workflow")


def _resolve_profile(
    config: WorkflowConfig,
    step: AgentDef,
    environment: ResolvedEnvironment,
) -> ResolvedStepProfile:
    step_profile = step.execution.profile if step.execution is not None else None
    workflow_execution = config.workflow.defaults.execution
    workflow_profile = workflow_execution.profile if workflow_execution is not None else None
    profile = step_profile or workflow_profile or environment.document.default
    if profile is None:
        raise ConfigurationError(
            f"Step '{step.name}' has no execution profile: "
            "set step.execution.profile, workflow.defaults.execution.profile, "
            "or environment.default."
        )

    definition = environment.document.profiles.get(profile)
    if definition is None:
        available = ", ".join(sorted(environment.document.profiles))
        raise ConfigurationError(
            f"Step '{step.name}' selects execution profile '{profile}', but "
            f"environment '{environment.name}' does not define it "
            f"(available: {available or '<none>'})."
        )
    return ResolvedStepProfile(profile=profile, backend=definition.backend)


def compile_run_manifest(
    config: WorkflowConfig,
    *,
    workflow_path: Path | None,
    environment: ResolvedEnvironment,
) -> ResolvedRunManifest:
    """Resolve every executable step against one environment document."""

    profiles: dict[str, ResolvedStepProfile] = {}

    def add(key: str, step: AgentDef) -> None:
        if key in profiles:
            raise ConfigurationError(
                f"Executable-step identity collision for '{key}'. "
                "Rename one of the colliding steps."
            )
        profiles[key] = _resolve_profile(config, step, environment)

    for step in config.agents:
        if _is_executable(step):
            add(executable_step_identity(step.name), step)

    for group in config.for_each:
        if _is_executable(group.agent):
            add(
                executable_step_identity(group.agent.name, for_each_group=group.name),
                group.agent,
            )

    workspace = config.workflow.workspace
    if workspace.mode != "shared":
        # WorkspaceConfig rejects this today; keep a defensive guard here so
        # the manifest compiler remains correct if it receives constructed or
        # future schema objects that bypass that validator.
        raise ConfigurationError(
            f"workspace mode '{workspace.mode}' is not supported by this execution build"
        )

    return ResolvedRunManifest(
        workflow=WorkflowIdentity(
            name=config.workflow.name,
            digest=_workflow_digest(workflow_path),
        ),
        environment=EnvironmentIdentity(
            name=environment.name,
            source=environment.source,
            digest=environment.digest,
        ),
        profiles=profiles,
        workspace=WorkspaceIdentity(
            mode="shared",
            persistence=workspace.persistence,
        ),
    )
