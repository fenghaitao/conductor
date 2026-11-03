# Codex SDK provider

The experimental `codex` provider runs the SDK-bundled Codex app-server. Install
it with `uv pip install 'conductor-cli[codex]'`, then select it with
`conductor run workflow.yaml --provider codex` (or the same flag on `resume`).
Native Codex inference remains the default and uses the normal Codex account
and configuration. Tools are scoped by the Codex sandbox; per-agent `tools:`
allowlists are unsupported. Agent `working_dir` applies on start, resume and
every turn. Conductor defaults to unattended `deny_all` approvals.

## GitHub Copilot through LiteLLM

This route keeps the Codex SDK agent loop and sends inference through an
already-running local LiteLLM proxy. It is distinct from Conductor's `copilot`
provider, which uses the Copilot SDK.

```sh
export CONDUCTOR_CODEX_BACKEND=copilot
export CONDUCTOR_CODEX_COPILOT_CATALOG=/absolute/path/codex_copilot_models.json
export COPILOT_PROXY_PORT=4000
export COPILOT_PROXY_API_KEY=your-proxy-key
conductor run workflow.yaml --provider codex
```

Alternatively, `AGENT_PROVIDERS_ROOT` selects the catalog at
`copilot/codex/codex_copilot_models.json` in that checkout. The port defaults
to 4000 and the local proxy key to `sk-local-proxy`. The route uses
`http://127.0.0.1:<port>/v1`, the Responses wire API, provider `github_copilot`,
and disables web search. Credentials reach the SDK child through its
environment, never through serialized public route settings. The SDK chooses
its bundled executable; no launcher or shared Codex configuration is changed.

An agent's model overrides the provider model. With neither supplied, Copilot
uses `gpt-6.1-sol`; native retains Codex's model default. Connection validation
makes a small real inference request on the Copilot route. A ChatGPT login or
a model catalog alone cannot satisfy it.

The probe always starts a fresh ephemeral thread in an empty temporary
directory with an explicit read-only sandbox and deny-all approvals. Both
thread creation and the inference turn use those limits, regardless of the
workflow provider's sandbox, working directory or restored agent sessions.

Before and after turns, including resume and output parse recovery, Conductor
checks the thread's provider and model. A missing/mismatched route, failed
resume or model-reroute notification fails without native fallback. Failed or
incomplete turns and parse recovery cannot produce a successful result.

New Conductor checkpoints save the selected backend and public catalog digest
under `provider_state.codex`. Resume restores and validates those settings
before provider construction or connection validation, even in a fresh shell
without backend variables. Proxy credentials still come from the environment.
Mixed-provider checkpoints retain session IDs from every active provider, so
Codex can reattach to its original thread even when another provider ran first.
Session restoration is checked per provider: a custom-routed, stateless default
skips session continuation without blocking resumable per-agent overrides.
Conflicting session IDs for the same agent refuse checkpoint creation with an
explicit error instead of writing ambiguous resume state.
Catalog drift and failed Copilot session resume fail without native fallback.
Native checkpoints also retain their native backend if the shell later selects
Copilot. Legacy checkpoints without provider settings retain their existing
environment-based behavior; supply the original backend explicitly for those.

## SDK compatibility and durable callers

The Codex extra supports SDK `>=0.163.0,<0.164`. Copilot startup cleanup has
an isolated compatibility adapter for this SDK's private transport. It retains
delayed process creation when cancellation wins, closes the eventual process
even after the event loop exits, and refuses unknown transport layouts.
The SDK compatibility CI job tests real transport code with fake process
creation and initialization; it makes no inference calls. A new SDK series
must pass these checks before the supported range is widened.

`conductor.providers.codex_backend.backend_settings` returns public route
settings, including the catalog's SHA-256. A durable caller can save those
settings and use `backend_environment` to restore the route and reject catalog
drift before launching. Secret values remain in the caller's environment.
Select `CONDUCTOR_CODEX_BACKEND=native` explicitly when replaying historical
native operations in an environment that might otherwise select Copilot.
