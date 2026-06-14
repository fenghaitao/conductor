# conductor-graph Architecture

## System Overview

The `conductor graph` command renders a static Mermaid `flowchart TD` diagram from a
workflow YAML file. It parses the workflow through the existing
`config/loader.py` → `WorkflowConfig` pipeline (reusing the same validation and
schema machinery as `conductor run`, `conductor validate`, and `conductor show`),
then walks the parsed configuration to produce a plain-text Mermaid diagram on
stdout. There is no workflow execution, no provider instantiation, and no new
dependencies — the output is pure Mermaid markdown that renders in GitHub,
Markdown viewers, and Mermaid Live.

The rendering is performed by a single pure function `render_mermaid(config, depth,
parent_dir) -> str` that lives in `src/conductor/cli/graph_cmd.py`. This function
has no side effects, no I/O, and no provider calls, making it trivially
unit-testable against golden-file output.

## Directory Structure

```
src/conductor/
├── cli/
│   ├── app.py                    # [MODIFIED] Register `graph` subcommand (2-3 lines)
│   ├── graph_cmd.py              # [NEW] Typer command group + render_mermaid() pure function
│   ├── run.py                    # (unchanged)
│   ├── validate.py               # (unchanged)
│   ├── bg_runner.py              # (unchanged)
│   ├── pid.py                    # (unchanged)
│   ├── update.py                 # (unchanged)
│   └── ...
├── config/
│   ├── schema.py                 # (unchanged — all step types already modeled)
│   ├── loader.py                 # (unchanged — reused for YAML → WorkflowConfig)
│   └── validator.py              # (unchanged)
├── engine/
│   └── ...                       # (unchanged)
└── registry/
    ├── resolver.py               # (unchanged — reused for ref → path resolution)
    └── cache.py                  # (unchanged — reused for registry fetch)

tests/
├── test_cli/
│   └── test_graph.py             # [NEW] CliRunner integration + render_mermaid() unit tests
├── fixtures/
│   └── graph/                    # [NEW] Golden Mermaid output files
│       ├── simple-qa-depth0.mmd
│       ├── parallel-research-depth0.mmd
│       ├── for-each-simple-depth0.mmd
│       ├── terminate-depth0.mmd
│       ├── script-step-depth0.mmd
│       ├── set-step-depth0.mmd
│       ├── wait-step-depth0.mmd
│       ├── simple-qa-depth1.mmd    # with sub-workflow inlining
│       └── ...
└── conftest.py                   # (unchanged)
```

## Data Models

The `graph` command reuses the existing Pydantic schema — no new models are needed.
All workflow topology information is already available in `WorkflowConfig`:

| Model | Key Fields Used |
|-------|----------------|
| `WorkflowConfig` | `.workflow.entry_point`, `.workflow.name`, `.agents`, `.parallel`, `.for_each` |
| `WorkflowDef` | `.entry_point`, `.name` |
| `AgentDef` | `.name`, `.type` (`agent`, `human_gate`, `script`, `set`, `wait`, `terminate`, `workflow`), `.workflow` (sub-workflow path), `.routes`, `.status` (for terminate) |
| `ParallelGroup` | `.name`, `.agents` (list of agent names), `.routes` |
| `ForEachDef` | `.name`, `.type`, `.agent` (inline AgentDef), `.routes` |
| `RouteDef` | `.to` (target name or `$end`), `.when` (condition expression) |

### Internal Data Model (graph_cmd.py only)

A lightweight internal representation is constructed for deterministic sorting:

```python
# Step nodes are sorted by name for deterministic output
# Each node maps to a Mermaid node definition with shape and style

# Node shapes by step type:
#   agent        → rect (default)
#   human_gate   → rhombus ({}),     class: "humanGate"
#   script       → hexagon ({{}}),   class: "scriptStep"
#   set          → stadium (([ ])),  class: "setStep"
#   wait         → cylinder [( )],   class: "waitStep"
#   terminate success → rounded rect with bold, class: "terminateSuccess"
#   terminate failed  → rounded rect with bold, class: "terminateFailed"
#   workflow     → subgraph (inlined) or rounded rect (opaque), class: "workflowStep"
#   $end         → stadium with double border, class: "endNode"

# Edges:
#   solid arrow for unconditional routes
#   labeled solid arrow for conditional routes: A -->|"condition"| B
#   dotted arrow for loop-back edges: A -.-> B
```

## API / Interface Layer

### CLI Command

```
conductor graph <workflow> [--output FILE] [--depth N]
```

**Arguments:**

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `workflow` | `str` (positional) | required | Workflow file path or registry reference (`name@registry@version`) |
| `--output` / `-o` | `Path` | stdout | Write diagram to file instead of stdout |
| `--depth` / `-d` | `int` | 1 | Recursive depth for sub-workflow inlining (0-10) |

**Input resolution** (same as `validate`, `show`, `run`):
1. Parse `workflow` through `resolve_ref()` from `conductor.registry.resolver`
2. If file ref: use path directly; if registry/adhoc: fetch via `resolve_and_fetch()` from `conductor.registry.cache`
3. Load config via `load_config()` from `conductor.config.loader`

**Output:**
- Plain Mermaid `flowchart TD` text on stdout (or `--output FILE`)
- Exit code 0 on success, 1 on error (missing file, parse failure, etc.)

**Error handling:**
- Registry resolution failure → `print_error()` + `typer.Exit(code=1)`
- YAML parse/schema failure → `print_error()` + `typer.Exit(code=1)`
- Missing sub-workflow file during `--depth > 0` → opaque error node in graph (never crashes)

### Registration in app.py

```python
# In src/conductor/cli/app.py — additive change only
from conductor.cli.graph_cmd import graph_app  # Typer app/command
app.add_typer(graph_app)  # or app.add_typer(graph_app, name="graph")
```

The `graph` command is a top-level Typer command (not a subcommand group) since it
has no sub-commands. It can be either:

- A standalone `@app.command()` in `graph_cmd.py` imported and registered in `app.py`
- A `typer.Typer` group registered via `app.add_typer()`

The recommended pattern (matching how `validate` and `show` work) is a single
`@app.command()` function defined in `graph_cmd.py` and registered in `app.py`.

## Service Layer

### `render_mermaid(config, depth, parent_dir) -> str`

Pure function — no I/O, no side effects, no provider calls.

**Signature:**
```python
def render_mermaid(
    config: WorkflowConfig,
    depth: int = 1,
    parent_dir: Path | None = None,
) -> str:
```

**Parameters:**
- `config`: Parsed `WorkflowConfig` from `load_config()`
- `depth`: Remaining recursion depth for sub-workflow inlining (decrements per level)
- `parent_dir`: Directory of the parent workflow file (for resolving relative sub-workflow paths)

**Algorithm:**

1. **Collect all steps**: Build a sorted list of all step names from `config.agents`,
   `config.parallel`, and `config.for_each`.

2. **Build the set of all valid targets**: All step names + `$end`. Used for
   edge validation and loop-back detection.

3. **Classify edges for loop-back detection**:
   - Compute a topological order by walking the DAG from `entry_point`
   - An edge `A → B` is a **loop-back** if `B` appears before or at `A` in the
     topological order (or if `B` is not reachable from `entry_point` in the
     forward direction without going through `A`)
   - Loop-back edges get dotted style (`-.->`)
   - All other edges get solid style (`-->`)

4. **Render nodes** (sorted by name for determinism):
   - Each step type gets a distinct Mermaid node shape
   - The `entry_point` gets a distinct CSS class (`entryPoint`) with bold border
   - `$end` is always included as a special node

5. **Render parallel groups as subgraphs**:
   ```
   subgraph parallel_researchers["Parallel: parallel_researchers"]
     direction LR
     academic_researcher
     web_researcher
     technical_researcher
   end
   ```
   Outbound edges are drawn FROM the subgraph name (not individual members).

6. **Render for-each groups as subgraphs**:
   ```
   subgraph item_processors["For-Each: item_processors (source: item_finder.output.topics)"]
     direction LR
     item_processor["item_processor (×N)"]
   end
   ```

7. **Render edges** (sorted by source, then target for determinism):
   - From each agent/group's `routes`
   - Conditional edges: `A -->|"condition"| B`
   - Unconditional edges: `A --> B`
   - Loop-back edges: `A -.-> B` or `A -.->|"condition"| B`

8. **Recursive sub-workflow inlining** (when `depth > 0`):
   - For each `type: workflow` agent:
     - Resolve the sub-workflow path relative to `parent_dir`
     - If the file exists and no cycle is detected (track visited paths):
       - Load the sub-workflow config via `load_config()`
       - Recurse with `render_mermaid(sub_config, depth - 1, sub_workflow_dir)`
       - Embed result as a nested Mermaid `subgraph`
     - If the file is missing or a cycle is detected:
       - Render an opaque error node: `workflow_name["⚠️ Missing: path"]`

9. **Cycle detection**:
   - Maintain a set of canonical paths (`Path.resolve()`) in the recursion stack
   - Before loading a sub-workflow, check if its resolved path is already in the set
   - If yes, emit an opaque node with `⚠️ Cycle: path` instead of recursing

10. **Output header and footer**:
    ```
    flowchart TD
      %% Generated by conductor graph
      %% Workflow: <name>
      %% Depth: <depth>

      classDef entryPoint stroke-width:3px
      classDef humanGate ...
      classDef scriptStep ...
      classDef setStep ...
      classDef waitStep ...
      classDef terminateSuccess ...
      classDef terminateFailed ...
      classDef workflowStep ...
      classDef endNode stroke-width:2px
      classDef errorNode stroke-dasharray: 5 5

      ... nodes ...
      ... subgraphs ...
      ... edges ...

      class <entry_point> entryPoint
    ```

### Deterministic Output

All iterations over dicts and sets are sorted by key/name:
- Agent names sorted alphabetically
- Route edges sorted by (source, target)
- Parallel group member names sorted
- For-each group names sorted
- Sub-workflow subgraphs sorted by agent name

This ensures golden-file tests are stable across runs.

## Infrastructure

- **No new dependencies.** Mermaid is plain text output.
- **No provider instantiation.** The command does not touch `providers/` at all.
- **No I/O in render path.** `render_mermaid()` is a pure function; file writing
  is handled by the CLI wrapper.
- **No dashboard changes.**
- **No API changes.**
- **No database or cache requirements.**

## Frontend Architecture

Not applicable. The output is plain text Mermaid markdown consumed by external
renderers (GitHub, Mermaid Live, Markdown viewers).

## Key Technical Decisions

### 1. Pure-function renderer for testability

`render_mermaid()` is a free function with no side effects. It takes a
`WorkflowConfig` and returns a `str`. This makes it trivially testable:
- Unit tests call `render_mermaid()` with in-memory `WorkflowConfig` objects
- Golden-file tests compare output against `.mmd` fixture files
- No mocking, no async, no I/O

### 2. Reuse existing config pipeline

The command reuses `config/loader.py` → `load_config()` → `WorkflowConfig` for
parsing, exactly like `validate` and `show`. This guarantees the graph command
sees the same validated topology as the execution engine — no divergence
possible.

### 3. Deterministic output via sorting

All collections are iterated in sorted order. This is critical for:
- Golden-file testing (no flaky diffs from hash ordering)
- Git diff friendliness (small workflow changes produce small, readable diffs)
- Reproducibility (same input always produces same output)

### 4. Loop-back detection via topological walk

Rather than requiring the user to annotate loop-back edges, the renderer walks
the DAG from `entry_point` to classify edges. An edge `A → B` is a loop-back if
`B`'s topological position is ≤ `A`'s. This handles all common loop-back patterns
(review → fix → review, quality_check → planner, etc.).

### 5. Graceful degradation for sub-workflows

Missing or cyclic sub-workflow files never crash the renderer. Instead, an
opaque error node is rendered in the graph, making the issue visible without
blocking the diagram for the rest of the workflow.

### 6. `--depth` default of 1

Default `--depth 1` means top-level `type: workflow` agents are inlined one
level deep. `--depth 0` shows them as opaque nodes. This matches user
expectations: most users want to see one level of sub-workflow detail without
exploding the diagram.

### 7. Mermaid node shapes by step type

Each step type gets a visually distinct shape so the diagram is readable at a
glance:

| Step Type | Mermaid Shape | Rationale |
|-----------|--------------|----------|
| agent (default) | `[name]` rectangle | Standard, neutral |
| human_gate | `{name}` rhombus | Decision/diamond → gate |
| script | `{{name}}` hexagon | Distinct, "external process" feel |
| set | `([name])` stadium | Rounded, "data" feel |
| wait | `[(name)]` cylinder | Database/delay connotation |
| terminate (success) | `name` rounded rect, green | Terminal success |
| terminate (failed) | `name` rounded rect, red | Terminal failure |
| workflow (opaque) | `name` rounded rect, blue | Black box |
| $end | `([$end])` stadium, double border | Terminal marker |

## Integration Points

### 1. Config Loading (shared with validate/show/run)

```
conductor.config.loader.load_config(path) → WorkflowConfig
```

The graph command calls `load_config()` exactly like `validate` and `show`. No
changes to the loader or schema.

### 2. Registry Resolution (shared with validate/show/run)

```
conductor.registry.resolver.resolve_ref(ref) → ResolvedRef
conductor.registry.cache.resolve_and_fetch(ref) → Path
```

Same resolution pipeline as all other commands. File refs, configured registry
refs, and ad-hoc GitHub refs are all supported.

### 3. CLI App Registration (additive change)

In `src/conductor/cli/app.py`, two lines added:
```python
from conductor.cli.graph_cmd import graph  # or graph_app
app.command()(graph)  # or app.add_typer(graph_app)
```

This is purely additive — no existing code is modified beyond the import and
registration.

### 4. No Integration With:
- **Engine** (`engine/workflow.py`): The graph command does not execute workflows
- **Providers** (`providers/`): No provider instantiation needed
- **Web dashboard** (`web/`): No dashboard changes
- **Events** (`events.py`): No event emission
- **Gates** (`gates/`): No human-in-the-loop interaction

## Worker Boundaries

This is a single-worker mission. All changes fall within one coherent scope:

| Component | File | Owner |
|-----------|------|-------|
| CLI command + renderer | `src/conductor/cli/graph_cmd.py` (new) | **graph-worker** |
| CLI registration | `src/conductor/cli/app.py` (additive 2-3 lines) | **graph-worker** |
| Tests | `tests/test_cli/test_graph.py` (new) | **graph-worker** |
| Golden fixtures | `tests/fixtures/graph/` (new) | **graph-worker** |

No other files are modified. No other workers are affected.

### Implementation Order

1. Create `graph_cmd.py` with `render_mermaid()` pure function
2. Write unit tests against `render_mermaid()` with in-memory `WorkflowConfig` objects
3. Create golden fixture files for each example workflow
4. Register the command in `app.py`
5. Write CliRunner integration tests
6. Run full test suite to verify no regressions
