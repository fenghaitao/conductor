# conductor-graph

## Why

Conductor workflows can span dozens of agents with parallel groups, for-each loops, conditional routes, human gates, terminate steps, and nested sub-workflows. Today, the only way to understand a workflow's topology is to read the YAML source directly — there is no visual or diagrammatic representation. This makes it hard to onboard new contributors, review workflow designs, document pipelines, or debug routing logic. A static graph-rendering command fills this gap: it produces a Mermaid `flowchart TD` diagram (pasteable into GitHub, Markdown, and docs) without executing the workflow, requiring no new dependencies, and reusing the existing `config/loader.py` → `WorkflowConfig` pipeline for correctness.

## What Changes

- New top-level CLI command `conductor graph <workflow>` that parses workflow YAML and emits a Mermaid `flowchart TD` diagram to stdout
- `--output FILE` flag to write the diagram to a file instead of stdout
- `--depth N` flag (default 1, min 0, max 10) to control recursive inlining of `type: workflow` sub-workflow agents as nested Mermaid subgraphs
- Accepts the same file-path and registry-ref (`name@registry@version`) input resolution as `conductor show`, `conductor validate`, and `conductor run`
- Pure-function renderer (`render_mermaid(config, depth, parent_dir) -> str`) in `src/conductor/cli/graph_cmd.py` — trivially unit-testable, no I/O in the render path
- Distinct Mermaid node shapes/classes for each step type: agent, script, set, wait, human_gate, terminate (success/failed), workflow, and `$end`
- `entry_point` marked visually with a distinct style (bold border)
- Labeled edges for conditional routes (`|"condition"|` syntax); dotted edges for loop-back routes
- Parallel groups and for-each groups rendered as Mermaid `subgraph` blocks with internal member nodes and outbound edges from the subgraph
- Recursive sub-workflow inlining with cycle detection and graceful missing-file degradation (opaque error node, never crash)
- Deterministic stable output (sorted by name) for reliable golden-file testing
- No new dependencies — Mermaid is plain text; no graphviz, no external libs, no provider instantiation

## Capabilities

### New Capabilities

- `workflow-graph`: Static rendering of workflow topology as a Mermaid `flowchart TD` diagram. Supports all step types (agent, script, set, wait, human_gate, terminate, workflow), parallel/for-each groups as subgraphs, conditional route edge labels, entry point highlighting, loop-back detection with dotted edges, recursive sub-workflow inlining with `--depth N`, cycle detection, missing-file degradation, deterministic output ordering, and `--output FILE` redirection. Accepts file paths and registry references.

### Modified Capabilities

<!-- No existing specs to modify. -->

## Impact

- **New file**: `src/conductor/cli/graph_cmd.py` — Typer command group + `render_mermaid()` pure function (~300-400 lines)
- **Modified file**: `src/conductor/cli/app.py` — register `graph` subcommand (additive, 2-3 lines)
- **New test file**: `tests/test_cli/test_graph.py` — CliRunner-based integration tests and unit tests for `render_mermaid()`
- **New test fixtures**: `tests/fixtures/graph/` — golden Mermaid output files for each example workflow at each depth
- **Dependencies**: None. Pure string building; reuses `config/loader.py`, `config/schema.py`, and `registry.resolver` / `registry.cache` (same as `validate` and `show`)
- **No API changes, no breaking changes, no provider changes, no dashboard changes**
