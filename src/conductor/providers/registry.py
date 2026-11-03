"""Provider registry for multi-provider workflow support.

This module provides the ProviderRegistry class for managing multiple
provider instances with lazy instantiation and caching.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Literal

from conductor.exceptions import CheckpointError
from conductor.providers.base import AgentProvider
from conductor.providers.factory import create_provider

if TYPE_CHECKING:
    from conductor.config.schema import AgentDef, WorkflowConfig


ProviderType = Literal[
    "copilot",
    "openai-agents",
    "claude",
    "pydantic-deep",
    "claude-agent-sdk",
    "claude-subscription",
    "codex",
]


class ProviderRegistry:
    """Manages multiple provider instances with lazy instantiation and caching.

    The ProviderRegistry enables multi-provider workflows where different
    agents can use different providers (e.g., Claude for research, Copilot
    for code generation). Providers are created lazily on first use and
    cached for subsequent agent executions.

    Example:
        >>> async with ProviderRegistry(config) as registry:
        ...     provider = await registry.get_provider(agent)
        ...     output = await executor.execute(agent, context)

    Key behaviors:
    - **Lazy creation**: Providers created on first agent that needs them
    - **Caching**: Same provider type reused across agents
    - **Lifecycle management**: Closes all providers at workflow end
    """

    def __init__(
        self,
        config: WorkflowConfig,
        mcp_servers: dict[str, Any] | None = None,
        skill_directories: list[str] | None = None,
    ) -> None:
        """Initialize the ProviderRegistry.

        Args:
            config: The workflow configuration.
            mcp_servers: MCP server configurations to pass to providers.
            skill_directories: Resolved skill directories to pass to the Copilot
                provider.  Paths must be absolute.
        """
        self._config = config
        self._mcp_servers = mcp_servers
        self._skill_directories = skill_directories
        self._providers: dict[ProviderType, AgentProvider] = {}
        self._default_provider_type: ProviderType = config.workflow.runtime.provider.name
        self._resume_session_ids: dict[str, str] = {}
        self._checkpoint_state: dict[str, dict[str, Any]] = {}

    @property
    def default_provider_type(self) -> ProviderType:
        """Get the default provider type from workflow config."""
        return self._default_provider_type

    def _get_provider_type_for_agent(self, agent: AgentDef) -> ProviderType:
        """Determine which provider type an agent should use.

        Args:
            agent: The agent definition.

        Returns:
            The provider type to use for this agent.
        """
        if agent.provider is not None:
            return agent.provider
        return self._default_provider_type

    async def get_provider(self, agent: AgentDef) -> AgentProvider:
        """Get the provider for an agent, creating it if necessary.

        This method resolves which provider the agent should use (based on
        agent.provider override or workflow default) and returns a cached
        or newly created provider instance.

        Args:
            agent: The agent definition.

        Returns:
            The AgentProvider instance for this agent.

        Raises:
            ProviderError: If provider creation fails.
        """
        provider_type = self._get_provider_type_for_agent(agent)
        return await self._get_or_create_provider(provider_type)

    async def _get_or_create_provider(self, provider_type: ProviderType) -> AgentProvider:
        """Get or create a provider of the specified type.

        Args:
            provider_type: The provider type to get or create.

        Returns:
            The AgentProvider instance.

        Raises:
            ProviderError: If provider creation fails.
        """
        if provider_type in self._providers:
            return self._providers[provider_type]

        # Create the provider with runtime config
        runtime = self._config.workflow.runtime
        # Only forward structured provider settings to the matching
        # provider — settings for Copilot must not bleed into a per-agent
        # Claude override (and vice versa once Claude grows its own
        # structured config).
        provider_settings = runtime.provider if runtime.provider.name == provider_type else None
        if provider_type == "codex" and provider_type not in self._checkpoint_state:
            from conductor.providers.codex_backend import backend_settings, resolve_backend

            # Connection validation performs inference. Retain its route even
            # when validation fails before the provider becomes active.
            self._checkpoint_state[provider_type] = {
                "backend_settings": backend_settings(resolve_backend())
            }
        checkpoint_kwargs: dict[str, Any] = {}
        if provider_type in self._checkpoint_state:
            checkpoint_kwargs["checkpoint_state"] = self._checkpoint_state[provider_type]
        provider = await create_provider(
            provider_type=provider_type,
            validate=True,
            mcp_servers=self._mcp_servers,
            default_model=runtime.default_model,
            temperature=runtime.temperature,
            max_tokens=runtime.max_tokens,
            timeout=runtime.timeout,
            max_session_seconds=runtime.max_session_seconds,
            max_agent_iterations=runtime.max_agent_iterations,
            default_reasoning_effort=runtime.default_reasoning_effort,
            skill_directories=self._skill_directories,
            provider_settings=provider_settings,
            **checkpoint_kwargs,
        )

        # Pass stored resume session IDs to newly created providers
        if self._resume_session_ids:
            self._apply_resume_session_ids(provider_type, provider)

        self._providers[provider_type] = provider
        return provider

    async def close(self) -> None:
        """Close all provider instances.

        This method should be called when the workflow completes to
        clean up all provider resources.
        """
        errors: list[Exception] = []
        for _provider_type, provider in self._providers.items():
            try:
                await provider.close()
            except Exception as e:
                # Collect errors but continue closing other providers
                errors.append(e)

        self._providers.clear()

        # Re-raise the first error if any occurred
        if errors:
            raise errors[0]

    async def __aenter__(self) -> ProviderRegistry:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - closes all providers."""
        await self.close()

    def get_active_providers(self) -> dict[ProviderType, AgentProvider]:
        """Get all currently active providers.

        Returns:
            Dictionary mapping provider type to provider instance.
        """
        return self._providers.copy()

    def is_provider_active(self, provider_type: ProviderType) -> bool:
        """Check if a provider type is currently active.

        Args:
            provider_type: The provider type to check.

        Returns:
            True if the provider is active, False otherwise.
        """
        return provider_type in self._providers

    def set_checkpoint_state(self, state: dict[str, dict[str, Any]]) -> None:
        """Restore public settings before creating or validating any provider."""
        if self._providers:
            raise ValueError("restore provider checkpoint settings before provider creation")
        self._checkpoint_state = copy.deepcopy(state)

    def get_checkpoint_state(self) -> dict[str, dict[str, Any]]:
        """Retain both restored settings and settings from active providers."""
        state = copy.deepcopy(self._checkpoint_state)
        for provider in self._providers.values():
            state.update(provider.get_checkpoint_state())
        return state

    def get_session_ids(self) -> dict[str, str]:
        """Collect every provider's sessions, refusing ambiguous agent identities.

        Active providers supersede their restored IDs. Retain restored IDs
        for providers that have not been instantiated on this resume yet.
        """
        sessions: dict[str, str] = {}
        owners: dict[str, str] = {}
        for provider_type, provider in self._providers.items():
            get_ids = getattr(provider, "get_session_ids", None)
            if not callable(get_ids):
                continue
            for agent_name, session_id in get_ids().items():
                if agent_name in sessions and sessions[agent_name] != session_id:
                    raise CheckpointError(
                        f"Conflicting checkpoint session IDs for agent {agent_name!r} "
                        f"from providers {owners[agent_name]!r} and {provider_type!r}"
                    )
                sessions[agent_name] = session_id
                owners[agent_name] = provider_type
        return self._resume_session_ids | sessions

    def _apply_resume_session_ids(
        self, provider_type: ProviderType, provider: AgentProvider
    ) -> None:
        """Apply saved IDs only when this provider's own route can resume."""
        settings = self._config.workflow.runtime.provider
        if settings.name == provider_type and settings.has_custom_routing():
            return
        restore = getattr(provider, "set_resume_session_ids", None)
        if callable(restore):
            restore(dict(self._resume_session_ids))

    def set_resume_session_ids(self, ids: dict[str, str]) -> None:
        """Store session IDs for every resumable provider.

        The IDs are forwarded to providers that support
        ``set_resume_session_ids`` — both already-active providers
        and providers created lazily in the future. Custom routing suppresses
        restoration only for the matching provider, never another override.

        Args:
            ids: Mapping of agent names to provider-native session IDs.
        """
        self._resume_session_ids = dict(ids)
        for provider_type, provider in self._providers.items():
            self._apply_resume_session_ids(provider_type, provider)
