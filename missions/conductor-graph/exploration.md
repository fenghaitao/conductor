# Exploration: conductor-graph

## What we're building

A new `conductor graph <workflow>` top-level CLI command that statically renders a workflow's topology as a Mermaid `flowchart TD` diagram — without executing it. The command:

- Parses workflow YAML via the existing `config/loader.py` → `WorkflowConfig` pipeline
- Walks agents, routes, parallel groups, for-each groups, human gates, terminate steps, set/script/wait steps, and sub-workflows (`type: workflow`)
- Emits Mermaid syntax to stdout (or `--output FILE`)
- Accepts the same file-or-registry-ref input resolution as `conductor show`
- Recursively inlines `type: workflow` agents as nested subgraphs with `--depth N` (default 1), cycle detection, and graceful missing-file degradation
- Marks `entry_point` distinctly, renders `$end`/`terminate` as distinct terminal nodes
- Produces deterministic output (stable node ordering) for reliable golden-file testing

**User flows:**
1. `conductor graph simple-qa.yaml` — see a flat linear workflow
2. `conductor graph parallel-research.yaml` — see parallel groups as subgraphs
3. `conductor graph mission/plan.yaml --depth 2` — see nested sub-workflows inlined
4. `conductor graph qa-bot@team@1.0.0` — resolve from registry, then render
5. `conductor graph workflow.yaml --output graph.md` — write to file

## Technology decisions

| Decision | Choice | Rationale |
|---|---|---|
| Output format | Mermaid `flowchart TD` only | Plain text, zero dependencies, pastes into GitHub/Markdown/docs. ASCII/DOT deferred. |
| Command surface | New top-level `conductor graph` command | Clean separation from `show`; room for graph-specific flags (`--depth`, `--output`). |
| Parser | Reuse `config/loader.py` → `WorkflowConfig` | No new parsing path; validated config already has all topology data. |
| Registry resolution | Reuse `registry.resolver.resolve_ref` + `registry.cache.resolve_and_fetch` | Same pattern as `show`, `validate`, `run`, `resume`. |
| Renderer architecture | Pure function `render_mermaid(config, depth) -> str` | Trivially unit-testable; no I/O in render path. |
| CLI framework | Typer (existing) | Same as all other commands in `app.py`. |
| Testing | `typer.testing.CliRunner` + golden-file assertions | Same pattern as `test_list.py`, `test_validate.py`. |
| No new dependencies | Plain string building | Mermaid is text; no graphviz, no external libs. |

## Architecture approach

### File layout
```
src/conductor/cli/
  graph_cmd.py          ← NEW: command + renderer (~300-400 lines)
  app.py                ← MODIFY: register graph command

tests/test_cli/
  test_graph.py         ← NEW: golden-file tests via CliRunner

tests/fixtures/graph/
  <workflow>-depth<N>.mermaid  ← NEW: golden Mermaid output files
```

### Command flow
```
CLI: conductor graph <workflow> [--depth N] [--output FILE]
  │
  ├─ 1. resolve_ref(workflow) → ResolvedRef
  ├─ 2. If registry/adhoc: resolve_and_fetch(ref) → Path
  ├─ 3. load_config(path) → WorkflowConfig
  ├─ 4. render_mermaid(config, depth, parent_dir=path.parent) → str
  └─ 5. Write to stdout or --output FILE
```

### Renderer design (`render_mermaid`)
The renderer is a pure function that walks `WorkflowConfig` and builds Mermaid syntax:

1. **Header**: `flowchart TD`
2. **Style declarations**: classDef blocks for node types (agent, script, set, wait, gate, terminate-success, terminate-failed, entry-point, subworkflow, end-node)
3. **Nodes**: Iterate `config.agents` in sorted order, emit each with appropriate shape based on `type`
4. **Edges**: For each agent with routes, emit `source --> target` edges. If route has `when:`, add edge label `|"condition"|`
5. **Parallel groups**: For each `config.parallel`, emit `subgraph group_name`, then member nodes + internal edges, then `end`. Route from subgraph to next.
6. **For-each groups**: Emit `subgraph group_name` with inline agent node + iteration label, route from subgraph to next.
7. **Entry point**: Add `style entry_point_name stroke-width:3px` or equivalent
8. **Recursion** (depth >= 1): For `type: workflow` agents, load child YAML via `load_config()`, inline as nested subgraph with `subgraph "label (sub)"`

### Node ID sanitization
Agent/group names are sanitized to Mermaid-safe IDs: replace non-alphanumeric chars with underscores, prefix with `n_` to avoid reserved words.

### Edge routing
- Normal forward edges: `A --> B`
- Loop-back edges (target appears earlier in topological order): `A --- B` (non-directional to reduce clutter) or `A -.-> B` (dotted)
- Edges from parallel/for-each subgraphs: connect to the subgraph ID, not internal nodes

## Infrastructure

No new services, ports, or external APIs. The command is entirely offline after YAML loading:
- **No provider instantiation** — skip `runtime.provider` entirely
- **No network** beyond existing `resolve_and_fetch` for registry refs (same as `show`)
- **No checkpoint writes** — read-only
- **No dashboard** — plain text stdout

## Milestones

### M1 — Command scaffold + flat render
- Create `src/conductor/cli/graph_cmd.py` with Typer `app`
- Register in `app.py` as `app.add_typer(graph_app, name="graph")`
- Input resolution: reuse `resolve_ref` + `resolve_and_fetch` pattern
- Core `render_mermaid(config, depth)` function
- Flat render: agents→nodes, entry_point marked, routes→labeled edges, `$end`/terminate→terminal
- `--output FILE` flag, exit codes (0=ok, 1=error)
- `--help` with examples

### M2 — Composite topology
- Parallel groups as Mermaid `subgraph` blocks
- For-each groups as Mermaid `subgraph` blocks
- Distinct node shapes for `human_gate`, `set`, `script`, `wait`, `terminate`
- Edges from subgraphs to route targets

### M3 — Recursion
- `--depth N` flag (default 1, min 0, max 10)
- `depth=0`: opaque node for `type: workflow`
- `depth>=1`: load child YAML (relative to parent), inline as nested subgraph
- Cycle detection via visited-path set
- Missing/unreadable file → opaque error node (never crash)
- Honor per-agent `max_depth`

### M4 — Output + UX polish
- `--output FILE` writes to file
- Deterministic stable ordering (sorted by name)
- Mermaid-safe escaping for labels, conditions, descriptions
- Integration testing against all example workflows
- Pass `make lint`, `make typecheck`, `make test`

## Worker types

Single worker type: **backend-worker** (Python). The entire feature is a pure CLI addition with no frontend, no TypeScript, no infrastructure changes.

## Testing surfaces

| Surface | Tool | What |
|---|---|---|
| Unit: renderer | pytest | Test `render_mermaid()` with synthetic `WorkflowConfig` objects; assert Mermaid string output |
| Integration: CLI | `CliRunner` | Invoke `conductor graph <fixture>` and assert stdout matches golden file |
| Golden files | `tests/fixtures/graph/` | Pre-computed Mermaid output for each example workflow at each depth |
| Edge cases | pytest | Cycle detection, missing sub-workflow file, `--depth 0`, `--depth 5` truncation, empty routes, terminate steps |
| Lint + typecheck | ruff + ty | `make lint && make typecheck` |
| Full suite | pytest | `make test` — must not regress existing tests |

**Test fixtures needed:**
- `examples/simple-qa.yaml` → `simple-qa-depth1.mermaid`
- `examples/parallel-research.yaml` → `parallel-research-depth1.mermaid`
- `examples/for-each-simple.yaml` → `for-each-simple-depth1.mermaid`
- `examples/terminate.yaml` → `terminate-depth1.mermaid`
- `examples/set-step.yaml` → `set-step-depth1.mermaid`
- `examples/script-step.yaml` → `script-step-depth1.mermaid`
- `examples/wait-step.yaml` → `wait-step-depth1.mermaid`
- `examples/mission/plan.yaml` → `plan-depth2.mermaid`
- Synthetic self-referential workflow → cycle handling
- Synthetic workflow with missing sub-workflow ref → error node

## Open risks

1. **Mermaid syntax edge cases**: Node labels containing quotes, backticks, or special characters (`<`, `>`, `{`, `}`) must be escaped. The renderer must handle Jinja2 template text in labels (e.g., `when: "{{ output.score >= 7 }}"`). Strategy: wrap all labels in double-quotes and escape internal double-quotes with `#quot;` or use HTML entities.

2. **Sub-workflow path resolution**: `type: workflow` agents reference paths relative to the parent YAML file. The renderer must track `parent_dir` through recursion to resolve child paths correctly — same as how `ConfigLoader` sets `_base_dir` for `!file` tags.

3. **Deterministic ordering**: Python dict ordering is insertion-ordered in 3.7+, but `WorkflowConfig` uses Pydantic models. The renderer must explicitly sort agent names, route lists, parallel group members, etc. to guarantee deterministic output across runs.

4. **Golden file maintenance**: When example workflows change, golden files must be regenerated. Consider a `--update-goldens` pytest flag or a script to regenerate them.

5. **Large workflows**: The mission/plan workflow has 7 sub-workflow agents, each referencing another YAML file. At `--depth 2`, this is ~15 files loaded. Performance should be fine (sub-second), but the Mermaid output may be large. Consider a `--max-nodes` guard if needed.

6. **`type: workflow` + `input_mapping`**: Sub-workflows may have different `input` schemas than their parent. The renderer doesn't execute `input_mapping`, so it cannot show data flow — only control flow. This is acceptable for v1 (static topology only).

7. **Backwards compatibility**: The `conductor graph` command must not break any existing command. Registration in `app.py` is additive only.
