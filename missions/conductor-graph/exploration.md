# Exploration: conductor-graph

## What we're building

A `conductor graph <workflow>` CLI command that statically renders a workflow's topology as a **Mermaid flowchart** without executing it. The command:

1. Accepts a workflow path or registry reference (same as `conductor show`).
2. Resolves it via the existing `resolve_ref()` → `resolve_and_fetch()` pipeline.
3. Loads the YAML via `config/loader.py` → `WorkflowConfig` Pydantic model.
4. Walks the config (agents, routes, parallel/for-each groups, gates, terminate, set/script/wait steps) and emits Mermaid `flowchart` syntax to stdout (or `--output FILE`).
5. With `--depth N`, recursively inlines `type: workflow` agents as nested subgraphs, with cycle detection and graceful degradation for missing files.

**Node/edge mapping:**
- LLM agents → rounded rectangles; entry_point → stadium shape (marked start)
- `$end` → circle terminal node; `type: terminate` → hexagon with status
- `type: script` → rectangle; `type: set` → parallelogram; `type: wait` → circle; `type: human_gate` → diamond (decision)
- Routes → labeled directed edges (unconditional `-->`, conditional `-->|when: condition|`)
- Parallel groups → `subgraph` containing agent nodes
- For-each groups → `subgraph` with inline agent + loop annotation
- `type: workflow` at depth=0 → opaque labeled node; at depth≥1 → inlined `subgraph`

## Technology decisions

- **Mermaid only** (plain text, zero dependencies, pastes into Markdown/GitHub). No ASCII/DOT in v1.
- **New `conductor graph` top-level command** in `src/conductor/cli/graph_cmd.py`, registered in `app.py` (NOT a flag on `show`).
- **No new dependencies** — Mermaid is just a string we emit.
- **Reuse `show`'s ref resolution**: `registry.resolver.resolve_ref` + `registry.cache.resolve_and_fetch`.
- **Pure function architecture**: `render_mermaid(config: WorkflowConfig, depth: int) -> str` — I/O-free for testability.

## Architecture approach

```
src/conductor/cli/graph_cmd.py   ← NEW: render_mermaid() + CLI command
src/conductor/cli/app.py         ← EDIT: register `graph` command
tests/test_cli/test_graph.py     ← NEW: CliRunner + golden-file assertions
```

The renderer:
1. Builds a name→item index from `config.agents`, `config.parallel`, `config.for_each`.
2. Starts BFS from `entry_point`, emits nodes and edges as discovered.
3. Sorts deterministically by name for stable output.
4. Mermaid-escapes all labels.
5. For recursion: tracks visited paths, loads child YAML relative to parent, wraps in subgraph.

## Infrastructure

- No external services or ports needed — this is a pure CLI read-only command.
- Uses existing registry cache (`~/.conductor/cache/registries/`) for registry references.
- Python 3.12+, Typer CLI, Pydantic v2 config models — all already in place.

## Milestones

1. **M1 — Command scaffold + flat render**: New `graph_cmd.py`, `app.py` registration, single-level rendering (agents, routes, `$end`/terminate), `--depth N`, `--output FILE`.
2. **M2 — Composite topology**: Parallel/for-each subgraphs, human gate diamonds, set/script/wait distinct shapes.
3. **M3 — Recursion**: `--depth N` inlining of `type: workflow`, cycle detection, missing file degradation.
4. **M4 — Output + UX**: `--help`, exit codes, Mermaid-safe escaping, golden-file tests.

## Worker types

- **backend-worker**: Python (Typer CLI, Pydantic config traversal, Mermaid string generation, Jinja2 for when-expression labeling).
- **testing-worker**: Pytest + CliRunner + golden-file assertions. Same Python test infrastructure as existing `test_validate.py`, `test_list.py`.

## Testing surfaces

- **Unit tests** (`tests/test_cli/test_graph.py`): CliRunner invocations against fixture workflows.
- **Golden-file assertions**: Compare rendered Mermaid output against expected strings for:
  - `examples/simple-qa.yaml` (linear)
  - `examples/parallel-research.yaml` (parallel groups)
  - `examples/for-each-simple.yaml` (for-each)
  - `examples/mission/plan.yaml` (nested sub-workflows, depth 1 and 2)
  - `examples/terminate.yaml` (terminate steps)
  - Registry reference resolution
  - Cycle detection (self-referential sub-workflow)
  - Missing file graceful degradation
- **CI**: `make lint`, `make typecheck`, `make test` must all pass.

## Open risks

1. **Mermaid label escaping**: `when:` conditions may contain pipes, quotes, braces, or angle brackets that break Mermaid syntax. Need robust escaping (e.g., wrap in quotes, escape internal quotes).
2. **Sub-workflow path resolution**: `type: workflow` agents have a `workflow:` field that may be relative to the parent YAML's directory. Must resolve correctly during recursion.
3. **Golden-file fragility**: If node ordering isn't deterministic, golden-file tests will flake. Must ensure stable sorting (by name, alphabetically).
4. **Gate option routing**: Human gates have `options[].route` — each option is effectively an edge from the gate to the target. These differ from regular agent `routes` and need distinct rendering logic.
5. **Depth 0 default**: The spec says default depth = 1 (inline one level). Must ensure depth=0 produces opaque nodes and depth=1 inlines one level — behavior must match spec precisely.
