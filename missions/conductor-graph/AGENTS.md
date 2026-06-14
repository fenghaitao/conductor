# AGENTS.md — `conductor graph` Mission

## Mission Boundaries

### Port Ranges
- **No new ports allocated.** `conductor graph` is a read-only CLI command that emits Mermaid text to stdout (or `--output FILE`) and exits. It does not start any servers or daemons.

### Directories OFF-LIMITS
- `src/conductor/engine/` — import only; no modifications. The graph command does not execute workflows.
- `src/conductor/web/` — do not touch.
- `src/conductor/providers/` — do not touch. No provider instantiation.
- `src/conductor/gates/` — do not touch.
- `src/conductor/events.py` — do not touch.
- `src/conductor/executor/` — do not touch.
- `~/.conductor/runs/` — do not read, write, or delete.
- `$TMPDIR/conductor/` — do not read, write, or delete.

### External Services
- **GitHub API** (HTTPS port 443) — only accessed indirectly via the existing `registry.cache.resolve_and_fetch` for registry refs (same as `show` and `validate`). Do not add new HTTP calls in `graph_cmd.py`.
- **No new network calls.** The command is entirely offline after YAML loading for file-path refs.

### Git Rules
- **Commit to:** this repository (`/home/hfeng1/conductor`), on the current branch.
- **Do NOT:**
  - Add new dependencies to `pyproject.toml`. Mermaid is plain text output; no graphviz, no external libs.
  - Modify files outside `src/conductor/cli/graph_cmd.py` (create) and `src/conductor/cli/app.py` (additive 2-3 line registration only).
  - Modify `src/conductor/config/schema.py`, `src/conductor/config/loader.py`, or `src/conductor/config/validator.py` — import only.
  - Modify `src/conductor/registry/` — import only (`resolver.resolve_ref`, `cache.resolve_and_fetch`).
  - Reformat or refactor existing code unrelated to the `graph` feature.

---

## Worker Guidance

### Technology Choices (BINDING — no substitutions)

| Requirement | Choice |
|---|---|
| CLI framework | **Typer** (`typer.Typer` group registered via `app.add_typer()`) |
| Output format | **Mermaid `flowchart TD`** — plain text string building, no external libraries |
| YAML/config loading | **`conductor.config.loader.load_config()`** → `WorkflowConfig` (reuse existing pipeline) |
| Input resolution | **`conductor.registry.resolver.resolve_ref()`** + **`conductor.registry.cache.resolve_and_fetch()`** (same as `validate`, `show`, `run`) |
| Error output | **`print_error()`** from `conductor.cli.app` for stderr; **`typer.Exit(code=1)`** for exit codes |
| File output | **`pathlib.Path.write_text()`** for `--output FILE` |
| Testing | **`typer.testing.CliRunner`** + golden-file assertions |

### Code Quality Standards

1. **Single new file.** All graph command logic lives in `src/conductor/cli/graph_cmd.py`. The pure-function renderer `render_mermaid(config, depth, parent_dir) -> str` is the core — it has no side effects, no I/O, no provider calls. The CLI wrapper (argument parsing, input resolution, file I/O) is the only part with side effects.

2. **Reuse, don't reimplement.** Import and call `load_config()`, `resolve_ref()`, `resolve_and_fetch()`, `print_error()` directly. Do not copy-paste their internals.

3. **Stay in scope.** This mission delivers a static graph-rendering CLI command. Do not:
   - Add fields to Pydantic schemas in `config/schema.py`.
   - Modify the workflow engine, providers, web dashboard, or gates.
   - Add new environment variables.
   - Change existing command behavior.
   - Instantiate any provider.

4. **Pure-function renderer.** `render_mermaid(config, depth, parent_dir) -> str` must have no side effects — no file I/O, no network, no random, no provider calls. This makes it trivially unit-testable with in-memory `WorkflowConfig` objects and golden-file comparisons.

5. **Deterministic output.** All iterations over dicts and sets must be sorted by key/name. Agent names, route edges, parallel group members, for-each groups, and sub-workflow subgraphs are all sorted alphabetically. Same input always produces byte-for-byte identical output.

6. **Type hints required.** All functions must have full type annotations (`from __future__ import annotations`). Run `make typecheck` before committing.

7. **Google-style docstrings.** Every public function and helper gets a docstring.

8. **No god files.** The `graph_cmd.py` module should be ~300-400 lines with clearly named internal helpers (e.g., `_render_node`, `_render_edges`, `_render_parallel_group`, `_render_for_each_group`, `_detect_loop_backs`, `_inline_subworkflow`). Extract reusable logic into small, focused functions.

### Commit Message Format

```
conductor graph: <brief description>

<optional body with details>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### Reporting Pre-Existing Bugs

If you encounter a bug in existing code (e.g., a crash in `load_config`, a resolver issue) that is NOT caused by your changes:

- **Do NOT fix it** in your changeset.
- **Document it** in the mission's `discoveredIssues` as a `non_blocking` note.
- Focus on the `graph` feature only.

---

## Known Pre-Existing Issues
- Pre-existing: test_restored_after_subworkflow_failure in tests/test_engine/test_subworkflow_skill_directories.py fails with ProviderError 'Simulated failure' — unrelated to graph feature

*(None documented yet — orchestrator fills this in during the run.)*

---

## Testing & Validation Guidance

### Running Tests (scoped to this feature)

```bash
# Run only the graph command tests
uv run pytest tests/test_cli/test_graph.py -v

# Run with coverage for the new module
uv run pytest tests/test_cli/test_graph.py --cov=conductor.cli.graph_cmd --cov-report=term-missing

# Run all CLI tests (to catch regressions)
uv run pytest tests/test_cli/ -v

# Run full test suite
make test
```

### Running Typecheck and Lint

```bash
# Type check (all code)
make typecheck

# Lint (all code)
make lint

# Auto-format before committing
make format

# Run all checks (lint + typecheck)
make check
```

### Testing Tools Available

- **`typer.testing.CliRunner`** — for invoking CLI commands in-process. Use `CliRunner(mix_stderr=False)` so you can assert on stdout vs stderr independently.
- **`pytest.tmp_path`** — for creating temp directories with `.yaml` workflow files.
- **Golden-file testing** — compare `render_mermaid()` output against `.mmd` fixture files in `tests/fixtures/graph/`. Use `Path.read_text()` for loading expected output.
- **In-memory `WorkflowConfig`** — construct `WorkflowConfig` objects directly in unit tests for `render_mermaid()` without touching the filesystem. Build `AgentDef`, `RouteDef`, `ParallelGroup`, `ForEachDef`, `WorkflowDef` Pydantic models programmatically.

### Manual Testing

```bash
# Basic linear workflow
uv run conductor graph examples/simple-qa.yaml

# With depth control
uv run conductor graph examples/simple-qa.yaml --depth 0
uv run conductor graph examples/simple-qa.yaml --depth 2

# Parallel groups
uv run conductor graph examples/parallel-research.yaml

# For-each groups
uv run conductor graph examples/for-each-simple.yaml

# Terminate steps
uv run conductor graph examples/terminate.yaml

# Script steps
uv run conductor graph examples/script-step.yaml

# Set steps
uv run conductor graph examples/set-step.yaml

# Wait steps
uv run conductor graph examples/wait-step.yaml

# Write to file
uv run conductor graph examples/simple-qa.yaml --output /tmp/test-graph.mmd

# Validate Mermaid syntax (paste output into https://mermaid.live)
uv run conductor graph examples/simple-qa.yaml | head -5

# Help
uv run conductor graph --help

# Error: missing file
uv run conductor graph nonexistent.yaml

# Error: invalid depth
uv run conductor graph examples/simple-qa.yaml --depth 11
uv run conductor graph examples/simple-qa.yaml --depth -1

# Error: invalid output path
uv run conductor graph examples/simple-qa.yaml --output /nonexistent/dir/out.mmd
```

### Expected Output Contracts

| Scenario | Exit 0 | Exit 1 | Stdout | Stderr |
|---|---|---|---|---|
| Valid workflow file | ✓ | | Valid Mermaid `flowchart TD` text | (empty) |
| Valid workflow + `--output FILE` | ✓ | | (empty — file written) | (empty) |
| Missing/invalid workflow file | | ✓ | (empty) | Formatted error via `print_error()` |
| `--depth` out of range (negative or >10) | | ✓ | (empty) | Range error message |
| `--output` to non-existent directory | | ✓ | (empty) | Path error message |
| Sub-workflow file missing during inlining | ✓ | | Full diagram with opaque error node | (empty — graceful degradation) |
| Sub-workflow cycle detected | ✓ | | Full diagram with opaque error node | (empty — graceful degradation) |
| `--help` | ✓ | | Help text with usage and examples | (empty) |

### Golden Fixture Files

Golden fixtures live in `tests/fixtures/graph/` as `.mmd` files. Naming convention:

```
<workflow-name>-depth<N>.mmd
```

Examples:
- `simple-qa-depth0.mmd`
- `simple-qa-depth1.mmd`
- `parallel-research-depth0.mmd`
- `for-each-simple-depth0.mmd`
- `terminate-depth0.mmd`
- `script-step-depth0.mmd`
- `set-step-depth0.mmd`
- `wait-step-depth0.mmd`

Each golden file is the complete Mermaid `flowchart TD` output (header, classDefs, nodes, edges, class assignments) that `render_mermaid()` should produce for the corresponding workflow at the specified depth. Regenerate golden files by running the command against the example workflow and piping to the fixture path — then manually verify the output is correct before committing.

### Validation Assertions (from features.yaml)

The test suite must cover all `VAL-*` assertions defined in `missions/conductor-graph/features.yaml`. Cross-reference each test case with the assertion it validates using comments or test IDs. Key categories:

- **VAL-CORE-001..003**: Basic rendering (entry point, $end node, unconditional edges)
- **VAL-CORE-004..010**: CLI flags (`--output`, `--depth` range, deterministic output)
- **VAL-CORE-005..007**: Sub-workflow inlining, depth control, graceful degradation
- **VAL-CROSS-001..002**: Error handling (missing file, invalid YAML, no tracebacks)
- **VAL-CROSS-003**: Distinct node shapes for all step types
- **VAL-CROSS-004**: Conditional edge labels and loop-back dotted edges
- **VAL-CROSS-005**: Recursive sub-workflow inlining
- **VAL-CROSS-006**: Parallel and for-each groups as subgraphs

---

## Implementation Order

1. **Create `src/conductor/cli/graph_cmd.py`** with `render_mermaid()` pure function and Typer command wrapper.
2. **Write unit tests** against `render_mermaid()` with in-memory `WorkflowConfig` objects.
3. **Create golden fixture files** for each example workflow at each depth.
4. **Register the command in `src/conductor/cli/app.py`** (`app.add_typer(graph_app)`).
5. **Write CliRunner integration tests** in `tests/test_cli/test_graph.py`.
6. **Run `make lint && make typecheck && make test`** to verify everything passes.

---

## Handoff Expectations

- When a feature is discovered to be already implemented, the worker must
  still produce a thorough handoff documenting: (a) where the implementation
  lives, (b) which existing tests cover it, (c) manual validation steps
  performed, and (d) explicit mapping to each listed validation assertion.
  This lets the orchestrator verify completeness without re-inspecting the
  codebase.

- Workers must not return a handoff with `return_to_orchestrator: false`
  when zero implementation progress has been made. If pre-reading existing
  code is required, the worker should do that as part of its execution loop
  and only hand off after producing tangible output (code, tests,
  verification). A handoff with empty `what_was_implemented` and empty
  `tests_added` is effectively a no-op and wastes orchestrator cycles.

---

## Mermaid Node Shape Reference

Each step type gets a visually distinct shape:

| Step Type | Mermaid Shape | CSS Class | Node Syntax |
|---|---|---|---|
| agent (default) | rectangle | (none) | `name["Label"]` |
| human_gate | rhombus | `humanGate` | `name{"Label"}` |
| script | hexagon | `scriptStep` | `name{{"Label"}}` |
| set | stadium | `setStep` | `name(["Label"])` |
| wait | cylinder | `waitStep` | `name[("Label")]` |
| terminate (success) | rounded rect | `terminateSuccess` | `name("Label")` |
| terminate (failed) | rounded rect | `terminateFailed` | `name("Label")` |
| workflow (opaque) | rounded rect | `workflowStep` | `name("Label")` |
| $end | stadium, double border | `endNode` | `end(["$end"])` |
| entry point | (same shape as type) | `entryPoint` (bold border) | (normal syntax + class assignment) |

### Edge Styles

| Edge Type | Mermaid Syntax |
|---|---|
| Unconditional forward | `A --> B` |
| Conditional forward | `A -->|"condition"| B` |
| Loop-back (unconditional) | `A -.-> B` |
| Loop-back (conditional) | `A -.->|"condition"| B` |
| Subgraph outbound | `group_name --> B` |

### Subgraph Syntax

```
subgraph group_id["Parallel: group_name"]
  direction LR
  member_a
  member_b
end
```

```
subgraph group_id["For-Each: group_name (source: agent.output.field)"]
  direction LR
  agent["agent (×N)"]
end
```

### Style Declarations

```
flowchart TD
  %% Generated by conductor graph
  %% Workflow: <name>
  %% Depth: <depth>

  classDef entryPoint stroke-width:3px
  classDef humanGate stroke:#e6a817,fill:#fff8e1
  classDef scriptStep stroke:#6c5ce7,fill:#f0edff
  classDef setStep stroke:#00b894,fill:#e6fff8
  classDef waitStep stroke:#0984e3,fill:#e8f4fd
  classDef terminateSuccess stroke:#00b894,fill:#e6fff8
  classDef terminateFailed stroke:#d63031,fill:#ffeaea
  classDef workflowStep stroke:#6c5ce7,fill:#f0edff,stroke-dasharray:5 5
  classDef endNode stroke-width:2px
  classDef errorNode stroke:#d63031,stroke-dasharray:5 5
```


### Graph Fixture Regeneration

When regenerating golden graph fixtures (`tests/fixtures/graph/*.mmd`), run `conductor graph examples/<wf>.yaml --depth N` for each depth and redirect stdout to the fixture file. The `%% Depth:` header comment reflects the remaining recursion depth at that render level — it decrements in nested sub-workflow subgraphs.


When a feature's implementation pre-exists (was already in the codebase before the feature was assigned), the worker should still add targeted tests and golden fixtures to lock in the behavior. The handoff should clearly state that the implementation was pre-existing so reviewers don't expect TDD-first ordering.


After a feature handoff verifies validation assertions, the orchestrator should update missions/*/validation-state.yaml to reflect the new status (pending → passed). The handoff for 4.1 confirms VAL-CORE-005, VAL-CORE-006, VAL-CROSS-005 are satisfied but validation-state.yaml still shows them as pending. This is a process gap — the validation state is the source of truth for which assertions have been verified.
