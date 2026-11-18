# Execution profiles, run manifest, and workspace lifecycle

This fork ports the first execution-architecture layer from upstream Conductor
without replacing the fork-specific Codex provider or Copilot backend work.

## Execution profiles

Executable steps may select a logical profile:

```yaml
workflow:
  defaults:
    execution:
      profile: vp

agents:
  - name: analyze
    prompt: Analyze the target repository.
    working_dir: "{{ workflow.input.vp_root }}"

  - name: test
    type: script
    execution:
      profile: test
    command: pytest
```

Profile resolution follows:

1. `step.execution.profile`
2. `workflow.defaults.execution.profile`
3. the selected environment document's `default`

Engine-local steps such as `wait`, `set`, `questions`, `human_gate`, and
`terminate` reject `execution:`.

Execution profiles and `working_dir` are deliberately separate. A profile
answers *how/where a step executes*; `working_dir` answers *which repository
or worktree the step operates on*. This keeps the existing AutoDML VP/worktree
model intact.

## Environment documents

Select an environment with:

```bash
conductor run workflow.yaml --environment autodml
conductor validate workflow.yaml --environment autodml
conductor resume workflow.yaml --environment autodml
```

A name is resolved with whole-document shadowing:

1. nearest project `.conductor/environments/<name>.yaml`
2. ancestor project locations up to the git root
3. `$CONDUCTOR_HOME/environments/<name>.yaml`

An explicit path may also be supplied. With no `--environment`, Conductor
uses the built-in `local/default` environment.

This PR intentionally registers only the `local` backend. Docker/ACA are
follow-up ports once the fork's Codex/provider behavior is rebased cleanly onto
this seam.

## Resolved run manifest

Each `WorkflowEngine` compiles a deterministic manifest before execution. The
root manifest is published under:

```text
workflow_started.system.execution_manifest
```

It records:

- workflow name and SHA-256 digest;
- environment name, source, and digest;
- the resolved profile/backend for each executable step;
- workspace mode and persistence policy.

The manifest contains no run ID, timestamp, workflow inputs, or absolute
environment-document path. It is an audit record of execution resolution, not
a runtime status object.

## Workspace lifecycle

The workflow schema now accepts:

```yaml
workflow:
  workspace:
    mode: shared
    persistence: ephemeral
```

`mode: isolated` remains reserved and is rejected.

The upstream persistence values `ephemeral`, `durable`, and `on-failure`
are represented in the schema and run manifest. This PR also introduces the
run-scoped `WorkspaceLease` lifecycle on the execution backend so allocation
and cleanup have a stable home.

**Important:** this PR does not yet create retained filesystem copies/volumes
for `durable` or `on-failure`. The local backend currently owns no retained
resource, so those values are audit intent only. A follow-up should port
upstream retained-local-workspace/run-bundle behavior rather than implementing
an ad-hoc copy of a VP worktree.

## Fork-specific compatibility

The provider axis remains independent from execution:

```text
execution profile -> backend (local today)
provider          -> copilot / claude / codex / ...
working_dir       -> VP/worktree path
```

No Codex provider or Copilot-through-LiteLLM code is removed or replaced by
this change.
