---
name: graph-worker
description: Implements the `conductor graph` CLI command that renders workflow YAML as a Mermaid flowchart TD diagram without executing workflows.
---

# Graph-Worker

NOTE: Startup and cleanup are handled by worker-base. This skill defines the WORK PROCEDURE.

## Required Skills and Tools

- **Filesystem tools**: Create `src/conductor/cli/graph_cmd.py` (new), modify `src/conductor/cli/app.py` (additive 2-3 lines), create `tests/test_cli/test_graph.py` (new), create golden fixtures in `tests/fixtures/graph/` (new).
- **Bash**: Run `uv run pytest`, `uv run ruff check`, `uv run ty` for type checking.
- **Python 3.12+**: Typer CLI command, Pydantic v2 models (`WorkflowConfig`, `AgentDef`, `ParallelGroup`, `ForEachDef`, `RouteDef`), pure-function renderer.
- **Existing config pipeline**: Reuse `conductor.config.loader.load_config()`, `conductor.registry.resolver.resolve_ref()`, `conductor.registry.cache.resolve_and_fetch()` — same as `validate` and `show`.
- **No new dependencies**: Mermaid is plain-text output. No graphviz, no external libs, no provider instantiation.

## Work Procedure

### Step 1: Understand Your Feature

Read the mission and architecture documents carefully. Key requirements:

- **New CLI command**: `conductor graph <workflow> [--output FILE] [--depth N]`
- **Pure-function renderer**: `render_mermaid(config, depth, parent_dir) -> str` in `graph_cmd.py` — no I/O, no side effects, trivially unit-testable.
- **Mermaid node shapes by step type**: agent (rect), human_gate (rhombus), script (hexagon), set (stadium), wait (cylinder), terminate success/failed (rounded rect with bold/green/red), workflow (rounded rect or subgraph), $end (stadium double border).
- **Entry point**: Bold border via CSS class `entryPoint`.
- **Conditional route edges**: Labeled with `-->|"condition"|` syntax.
- **Loop-back edges**: Dotted arrows (`-.->`) detected via topological walk from entry_point.
- **Parallel/for-each groups**: Rendered as Mermaid `subgraph` blocks with outbound edges from the subgraph.
- **Recursive sub-workflow inlining**: `--depth N` (default 1, 0-10). Cycle detection via canonical path set. Missing files → opaque error node.
- **Deterministic output**: All collections sorted by name for golden-file stability.
- **Input resolution**: Same file-path and registry-ref (`name@registry@version`) as `validate`, `show`, `run`.

Fulfills assertions:
- `workflow-graph` capability: All step types rendered, parallel/for-each as subgraphs, conditional edges, entry point highlighting, loop-back detection, recursive inlining with depth, cycle detection, missing-file degradation, deterministic ordering, `--output FILE` redirection.

### Step 2: Test First (TDD)

Write failing tests before writing implementation code.

Create `tests/test_cli/test_graph.py`:

**Unit tests for `render_mermaid()`**:
- `test_render_minimal_workflow` — single agent → one node, $end node, edge from agent to $end.
- `test_render_entry_point_highlighted` — entry_point node gets `class <name> entryPoint` line.
- `test_render_agent_shapes` — each step type (agent, human_gate, script, set, wait, terminate success, terminate failed, workflow) produces correct Mermaid shape syntax.
- `test_render_conditional_routes` — edge with `when` condition gets labeled arrow: `A -->|"condition"| B`.
- `test_render_unconditional_routes` — edge without `when` gets plain arrow: `A --> B`.
- `test_render_loop_back_detection` — A → B → A produces dotted edge `A -.-> B` on the return path.
- `test_render_parallel_group_subgraph` — parallel group renders as `subgraph` with member nodes inside, outbound edge from subgraph.
- `test_render_for_each_group_subgraph` — for-each group renders as `subgraph` with inline agent, source annotation.
- `test_render_terminate_success_and_failed` — terminate nodes get distinct CSS classes and rounded rect shape.
- `test_render_end_node` — `$end` always present with stadium shape and double border class.
- `test_render_deterministic_ordering` — same input produces identical output across multiple calls.
- `test_render_multiple_routes_sorted` — edges sorted by source then target.
- `test_render_depth_zero_subworkflow_opaque` — depth=0: workflow agent renders as opaque rounded rect.
- `test_render_depth_one_subworkflow_inlined` — depth=1: workflow agent inlined as nested subgraph.
- `test_render_subworkflow_file_missing` — missing sub-workflow file → error node, no crash.
- `test_render_subworkflow_cycle_detection` — cyclic sub-workflow references → error node, no infinite recursion.
- `test_render_header_and_class_defs` — output starts with `flowchart TD`, includes classDef lines.
- `test_render_no_orphan_edges` — every edge target exists as a node or subgraph.

**Integration tests via CliRunner**:
- `test_cli_graph_file_path` — `conductor graph examples/simple-qa.yaml` succeeds, outputs valid Mermaid.
- `test_cli_graph_output_file` — `--output /tmp/test.mmd` writes to file, no stdout.
- `test_cli_graph_depth_flag` — `--depth 0` vs `--depth 2` produce different output.
- `test_cli_graph_invalid_file` — non-existent file exits with code 1 and error message.
- `test_cli_graph_invalid_yaml` — malformed YAML exits with code 1.
- `test_cli_graph_registry_ref` — registry reference resolves and renders (if registry available).

Run: `uv run pytest tests/test_cli/test_graph.py -v` — expect all tests to FAIL (no implementation yet).

### Step 3: Implement

**Create `src/conductor/cli/graph_cmd.py`**:

Structure:
```python
"""Graph command — render workflow topology as Mermaid flowchart TD."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from conductor.config.loader import load_config
from conductor.registry.resolver import resolve_ref
from conductor.registry.cache import resolve_and_fetch

if TYPE_CHECKING:
    from conductor.config.schema import WorkflowConfig

# --- Pure-function renderer ---

def render_mermaid(
    config: WorkflowConfig,
    depth: int = 1,
    parent_dir: Path | None = None,
    _visited: set[Path] | None = None,
) -> str:
    """Render a WorkflowConfig as a Mermaid flowchart TD diagram.

    Pure function — no I/O, no side effects.

    Args:
        config: Parsed workflow configuration.
        depth: Remaining recursion depth for sub-workflow inlining.
        parent_dir: Directory of the parent workflow file (for resolving
            relative sub-workflow paths).
        _visited: Internal cycle-detection set of canonical resolved paths.

    Returns:
        Mermaid flowchart TD diagram as a string.
    """
    # Implementation follows architecture.md algorithm:
    # 1. Collect all steps, build sorted list
    # 2. Build set of valid targets (names + $end)
    # 3. Topological walk from entry_point to classify loop-back edges
    # 4. Render nodes by type with correct Mermaid shapes
    # 5. Render parallel groups as subgraphs
    # 6. Render for-each groups as subgraphs
    # 7. Render edges (sorted, conditional labels, loop-back dotted)
    # 8. Recursive sub-workflow inlining when depth > 0
    # 9. Cycle detection via _visited set
    # 10. Output header, classDefs, nodes, subgraphs, edges, class assignments
    ...

# --- CLI command ---

@app.command(name="graph")
def graph(
    workflow: str = typer.Argument(..., help="Workflow file path or registry reference"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write diagram to file"),
    depth: int = typer.Option(1, "--depth", "-d", min=0, max=10, help="Sub-workflow inlining depth"),
) -> None:
    """Render a workflow as a Mermaid flowchart TD diagram."""
    # 1. Resolve input (file path or registry ref)
    # 2. Load config via load_config()
    # 3. Call render_mermaid()
    # 4. Write to stdout or --output file
    # 5. Error handling: print_error() + typer.Exit(code=1)
    ...
```

**Modify `src/conductor/cli/app.py`** (additive only):
```python
from conductor.cli.graph_cmd import graph
# Register the graph command — e.g., app.command()(graph)
```

**Key implementation details**:

1. **Node shape mapping** (in `render_mermaid`):
   ```python
   _NODE_SHAPES = {
       "agent": '{}["{}"]',           # rectangle
       "human_gate": '{}{{{}}}',       # rhombus
       "script": '{{{{"{}"}}}}',      # hexagon
       "set": '(["{}"])',             # stadium
       "wait": '[("{}")]',            # cylinder
       "terminate": '{}["{}"]',       # rounded rect via CSS
       "workflow": '{}["{}"]',        # rounded rect via CSS
       "$end": '(["$end"])',           # stadium
   }
   ```

2. **Topological walk for loop-back detection**:
   - BFS/DFS from `entry_point` recording visit order
   - Edge `A → B` is loop-back if `order[B] <= order[A]`
   - Unreachable-from-entry nodes: edges to them are not loop-backs (normal forward edges from reachable sources)

3. **CSS class definitions** (included in every output):
   ```
   classDef entryPoint stroke-width:3px
   classDef humanGate stroke:#9c27b0,fill:#f3e5f5
   classDef scriptStep stroke:#ff9800,fill:#fff3e0
   classDef setStep stroke:#4caf50,fill:#e8f5e9
   classDef waitStep stroke:#607d8b,fill:#eceff1
   classDef terminateSuccess stroke:#2e7d32,fill:#e8f5e9
   classDef terminateFailed stroke:#c62828,fill:#ffebee
   classDef workflowStep stroke:#1565c0,fill:#e3f2fd
   classDef endNode stroke-width:2px
   classDef errorNode stroke-dasharray:5 5,stroke:#c62828
   ```

4. **Sub-workflow inlining**:
   - Resolve path relative to `parent_dir`
   - Check `Path.resolve()` against `_visited` for cycle detection
   - Load via `load_config()` wrapped in try/except
   - On success: recurse with `render_mermaid(sub_config, depth-1, sub_dir, _visited | {resolved_path})`
   - On failure: emit `sub_name["⚠️ Missing: path"]` with `errorNode` class

5. **Deterministic ordering**: Use `sorted()` on all dict keys, lists, and sets before iteration.

### Step 4: Verify

Run scoped commands:

```bash
# Unit + integration tests (scoped to graph)
uv run pytest tests/test_cli/test_graph.py -v

# Type check (scoped to CLI directory)
uv run ty check src/conductor/cli/

# Lint (scoped to changed files)
uv run ruff check src/conductor/cli/graph_cmd.py src/conductor/cli/app.py tests/test_cli/test_graph.py

# Format check
uv run ruff format --check src/conductor/cli/graph_cmd.py src/conductor/cli/app.py tests/test_cli/test_graph.py
```

Fix all failures before proceeding.

Then run full suite at milestone boundary:
```bash
uv run pytest -v
uv run ruff check
uv run ty check
```

### Step 5: Manual Verification

1. **Basic workflow**: `uv run conductor graph examples/simple-qa.yaml` — verify Mermaid output starts with `flowchart TD`, includes classDefs, agent node, $end node, and edge.

2. **Output to file**: `uv run conductor graph examples/simple-qa.yaml --output /tmp/test.mmd && cat /tmp/test.mmd` — verify file contents match stdout.

3. **Depth control**: Run with `--depth 0`, `--depth 1`, `--depth 2` on a workflow with sub-workflows — verify deeper depth produces more inlined subgraphs.

4. **Error handling**: `uv run conductor graph nonexistent.yaml` — verify exit code 1 and error message.

5. **Copy-paste into Mermaid Live** (https://mermaid.live): Paste the output and verify it renders without syntax errors, showing correct node shapes, edge labels, subgraphs, and class styling.

6. **Golden-file comparison**: Run against each example workflow at depth 0 and 1, compare against `tests/fixtures/graph/*.mmd` — output must match exactly.

7. **Determinism**: Run the same command twice — output must be byte-identical.

## Example Handoff

CRITICAL: The Example Handoff section sets the upper bound of expected worker effort.
Make it realistic, specific, and thorough. Workers pattern-match against it —
the effort level shown here is the effort level you will receive.
A thin example produces thin implementations; a thorough example produces thorough ones.

salient_summary: "Implemented `conductor graph` CLI command with Mermaid flowchart TD rendering"
what_was_implemented: >
  Created `src/conductor/cli/graph_cmd.py` with `render_mermaid()` pure function (~350 lines)
  and Typer `graph` command. The renderer walks a parsed `WorkflowConfig` to produce a
  Mermaid `flowchart TD` diagram with distinct node shapes per step type (agent: rect,
  human_gate: rhombus, script: hexagon, set: stadium, wait: cylinder, terminate: rounded
  rect, workflow: rounded rect, $end: stadium double border). Entry point highlighted via
  `entryPoint` CSS class (bold border). Conditional routes labeled with `-->|"condition"|`
  syntax. Loop-back edges detected via topological walk from entry_point and rendered as
  dotted arrows (`-.->`). Parallel groups and for-each groups rendered as Mermaid `subgraph`
  blocks with outbound edges from the subgraph. Recursive sub-workflow inlining via
  `--depth N` (default 1, 0-10) with cycle detection (canonical path set) and missing-file
  degradation (opaque error node, never crashes). Deterministic output via sorted iteration
  for golden-file stability. `--output FILE` flag writes to file instead of stdout.
  Registered `graph` command in `src/conductor/cli/app.py` (additive 2 lines). Input
  resolution reuses existing `resolve_ref()` / `resolve_and_fetch()` pipeline (same as
  validate/show/run). No new dependencies — pure text output.
what_was_left_undone: ""
verification:
  commands_run:
    - command: "uv run pytest tests/test_cli/test_graph.py -v"
      exit_code: 0
      observation: "All graph tests pass (unit + integration)"
    - command: "uv run ty check src/conductor/cli/"
      exit_code: 0
      observation: "No type errors in CLI directory"
    - command: "uv run ruff check src/conductor/cli/graph_cmd.py src/conductor/cli/app.py tests/test_cli/test_graph.py"
      exit_code: 0
      observation: "No lint violations"
    - command: "uv run ruff format --check src/conductor/cli/graph_cmd.py src/conductor/cli/app.py tests/test_cli/test_graph.py"
      exit_code: 0
      observation: "Code is properly formatted"
    - command: "uv run pytest -v"
      exit_code: 0
      observation: "Full test suite passes — no regressions"
  interactive_checks:
    - action: "uv run conductor graph examples/simple-qa.yaml"
      observed: "Mermaid flowchart TD output with agent node, $end node, classDefs, and edge"
    - action: "uv run conductor graph examples/simple-qa.yaml --output /tmp/test.mmd && cat /tmp/test.mmd"
      observed: "File contains same Mermaid output as stdout"
    - action: "uv run conductor graph examples/simple-qa.yaml --depth 0"
      observed: "Shallower output with fewer subgraphs than depth 1"
    - action: "uv run conductor graph nonexistent.yaml"
      observed: "Exit code 1 with error message on stderr"
    - action: "Paste output into https://mermaid.live"
      observed: "Diagram renders without syntax errors, correct shapes and styling"
    - action: "Run same command twice, diff outputs"
      observed: "Byte-identical output (deterministic)"
tests_added:
  - file: "tests/test_cli/test_graph.py"
    cases:
      - name: "test_render_minimal_workflow"
        description: "Single agent produces one node, $end node, and edge to $end"
      - name: "test_render_entry_point_highlighted"
        description: "Entry point node gets entryPoint CSS class assignment"
      - name: "test_render_agent_shapes"
        description: "Each step type produces correct Mermaid shape syntax"
      - name: "test_render_conditional_routes"
        description: "Edges with when conditions get labeled arrow syntax"
      - name: "test_render_unconditional_routes"
        description: "Edges without when get plain arrow syntax"
      - name: "test_render_loop_back_detection"
        description: "Loop-back edges detected via topological walk, rendered dotted"
      - name: "test_render_parallel_group_subgraph"
        description: "Parallel group renders as subgraph with members and outbound edges"
      - name: "test_render_for_each_group_subgraph"
        description: "For-each group renders as subgraph with inline agent and source annotation"
      - name: "test_render_terminate_success_and_failed"
        description: "Terminate nodes get distinct CSS classes and rounded rect shape"
      - name: "test_render_end_node"
        description: "$end always present with stadium shape and endNode class"
      - name: "test_render_deterministic_ordering"
        description: "Same input produces identical output across multiple calls"
      - name: "test_render_multiple_routes_sorted"
        description: "Edges sorted by source then target"
      - name: "test_render_depth_zero_subworkflow_opaque"
        description: "Depth 0 shows workflow agent as opaque rounded rect"
      - name: "test_render_depth_one_subworkflow_inlined"
        description: "Depth 1 inlines sub-workflow as nested subgraph"
      - name: "test_render_subworkflow_file_missing"
        description: "Missing sub-workflow file produces error node, no crash"
      - name: "test_render_subworkflow_cycle_detection"
        description: "Cyclic references produce error node, no infinite recursion"
      - name: "test_render_header_and_class_defs"
        description: "Output starts with flowchart TD, includes classDef lines"
      - name: "test_render_no_orphan_edges"
        description: "Every edge target exists as a node or subgraph"
      - name: "test_cli_graph_file_path"
        description: "CLI accepts file path, outputs valid Mermaid"
      - name: "test_cli_graph_output_file"
        description: "--output flag writes to file instead of stdout"
      - name: "test_cli_graph_depth_flag"
        description: "--depth 0 vs --depth 2 produce different output"
      - name: "test_cli_graph_invalid_file"
        description: "Non-existent file exits code 1 with error"
      - name: "test_cli_graph_invalid_yaml"
        description: "Malformed YAML exits code 1 with error"
      - name: "test_cli_graph_registry_ref"
        description: "Registry reference resolves and renders"
  - file: "tests/fixtures/graph/"
    cases:
      - name: "simple-qa-depth0.mmd"
        description: "Golden output for simple-qa.yaml at depth 0"
      - name: "simple-qa-depth1.mmd"
        description: "Golden output for simple-qa.yaml at depth 1"
      - name: "parallel-research-depth0.mmd"
        description: "Golden output for parallel-research.yaml at depth 0"
      - name: "for-each-simple-depth0.mmd"
        description: "Golden output for for-each-simple.yaml at depth 0"
      - name: "terminate-depth0.mmd"
        description: "Golden output for terminate.yaml at depth 0"
      - name: "script-step-depth0.mmd"
        description: "Golden output for script-step.yaml at depth 0"
      - name: "set-step-depth0.mmd"
        description: "Golden output for set-step.yaml at depth 0"
      - name: "wait-step-depth0.mmd"
        description: "Golden output for wait-step.yaml at depth 0"
return_to_orchestrator: false
discovered_issues: []
skill_name: "graph-worker"
skill_feedback: []
