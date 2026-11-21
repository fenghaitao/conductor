# Antigravity provider assessment

**Recommendation** — Prototype an experimental provider using headless `agy`
when workflow output schemas are the priority. ACP is viable when explicit
tool approval, workflow MCP, and session control matter more. The Python SDK
can serve text and structured-output steps through LiteLLM. Tool-capable SDK
sessions need a translation fix.

The 2026-11-20 assessment tested `agy` 1.5.13 and `google-antigravity`
0.1.24 against Gemini 4 Argon through the CTH Chat Completions gateway.

## Python SDK and LiteLLM

- Setting `AGY_LLM_GATEWAY_*` in the SDK parent and child environments
  produced zero gateway requests. With a dummy Gemini key, the runtime
  attempted the native Google API. Loopback controls confirmed that
  `GeminiAPIEndpoint` and `VertexEndpoint` send native
  `streamGenerateContent?alt=sse` requests. The authenticated upstream
  returned HTTP 404 for all 16 native path and method combinations, and
  HTTP 200 for the Chat Completions control.
  [SDK package](https://pypi.org/project/google-antigravity/0.1.24/) ·
  [GenerateContent reference](https://ai.google.dev/api/generate-content)
- LiteLLM 1.100.1 translated the native `generateContent` and
  `streamGenerateContent` routes using the existing bridge config and
  `openai/gemini-4-argon` deployment. The SDK streamed text and returned
  schema-constrained output with `GeminiAPIEndpoint.base_url` set to the
  LiteLLM root. The tested Vertex path returned HTTP 404 on LiteLLM.
  [LiteLLM router endpoints](https://docs.litellm.ai/docs/tutorials/google_genai_sdk#advanced-use-any-model-with-the-genai-sdk)
- In a live tool turn, the SDK sent its `functionResponse` under role
  `model`. LiteLLM dropped that result, rewrote the call ID, and omitted the
  thought signature. The gateway could not recover the signature by ID, and
  the follow-up returned HTTP 400. A fixture also found duplicate IDs for
  parallel calls to the same function and no mapping from native thinking
  level to `reasoning_effort`. The LiteLLM 1.110.2 source still contains the
  same tool conversion behavior. YAML parameter settings cannot recover the
  missing data. An adapter fix needs to preserve tool results, call IDs, and
  signatures across streaming and resume.
  [LiteLLM adapter](https://github.com/BerriAI/litellm/blob/v1.110.2/litellm/google_genai/adapters/transformation.py#L196-L267) ·
  [Thought signatures](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking/thought-signatures)

## Headless CLI

- NDJSON input and output supported live text, a file-tool round trip, and
  cross-process resume. Use one workflow prompt per launch with `--json-schema`
  and validate the terminal `structured_output`. A multi-prompt schema run
  returned a stale result and an error. A resume without a schema could still
  carry prior structured output.
- A missing `--conversation` ID started a new session and exited successfully.
  Check the `init` conversation ID before writing the prompt. Launch in the
  resolved `working_dir`. A persistent child home isolated
  `~/.gemini/antigravity-cli` state and preserved resume. The CLI ignored
  `GEMINI_HOME`.
- Use scoped permissions for unattended runs. A denied command emitted a tool
  error while the turn exited successfully. On this gateway, `--mode auto`
  warned and reverted to default. Map text deltas and tool state changes to
  Conductor events. Usage counters are cumulative, and the stream exposes
  only some model-call boundaries. Workflow MCP, tool allowlists, reasoning
  events, and parallel safety remain unverified.
  [Headless CLI](https://antigravity.google/docs/cli/headless/)

## Agent Client Protocol

- Conductor can launch `agy acp` and use `agent-client-protocol` for JSON-RPC
  over stdio. The agent uses the same Chat Completions gateway. Live probes
  pinned Argon and low reasoning effort, read a workspace file, rejected a
  shell action, and ran a stdio MCP tool after `allow_once`. Typed tool updates
  and permission requests map to Conductor events and approval handling.
- A fresh subprocess restored the conversation with `session/resume` and
  recalled earlier context without replaying the transcript. An unknown ID
  returned an error. `session/cancel` returned `cancelled` before the turn
  reached the gateway. `agy` returned input and output token counts in a
  prompt-response extension. ACP has no response-schema parameter, so
  Conductor would prompt for JSON and validate it locally.
  [Antigravity ACP](https://antigravity.google/docs/ide/extensions/acp/) ·
  [ACP session setup](https://agentclientprotocol.com/protocol/v1/session-setup) ·
  [ACP prompt schema](https://agentclientprotocol.com/protocol/v1/schema#promptresponse)

For either CLI transport, store the conversation ID in the existing checkpoint
session map. Freeze the public gateway route, model catalog, and profile identity
in `provider_state.agy`. Revalidate them on resume, resolve the gateway key
separately, and use gateway evidence for route and model attestation.
