# Mission: `conductor-graph`

**Date:** 2026-06-14
**Status:** Design approved — ready to feed into `examples/mission/plan.yaml`

## Problem

Conductor has no way to *see* a workflow's topology without running it. `conductor
show` lists a workflow's name, description, and input parameters but never draws the
graph of agents, routes, parallel groups, for_each loops, gates, or terminate steps.
`conductor replay` visualizes a *recorded run* but requires a browser and an
already-executed event log. There is no static, terminal-friendly, browser-free way
to understand or document a workflow's control flow.

## Goal

Add a `conductor graph <workflow>` command that statically renders a workflow's
topology as a **Mermaid** flowchart — without executing it.

## Idea (seed for `plan.yaml --input idea=...`)

> Add a `conductor graph <workflow>` command that statically renders a workflow's
> topology as a Mermaid flowchart — without executing it. It parses the YAML via the
> existing `config/loader.py` → `WorkflowConfig`, walks agents/routes/parallel-groups/
> for_each/gates/terminate, and emits Mermaid `flowchart` syntax to stdout (or
> `--output FILE`). Routes render as labeled edges (the `when:` condition as the
> label); `$end`/terminate are distinct terminal nodes; parallel groups and for_each
> render as subgraphs. With `--depth N` it recurses into `type: workflow` agents,
> inlining sub-workflow topology as nested subgraphs up to depth N (default 1),
> guarding against cycles and missing files. Accepts the same file-or-registry-ref
> input resolution as `show`.

## Locked Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Output format | **Mermaid only** | Plain text, zero render dependency, pastes into Markdown/GitHub/docs. ASCII/DOT deferred (YAGNI). |
| Command surface | **New `conductor graph` command** | Clean separation from `show`; room for graph-specific flags. Matches the `list` mission's pattern. |
| Sub-workflow handling | **Recursive with `--depth N`** | Workflows like `examples/mission/plan.yaml` nest `type: workflow` agents; inlining their topology is the high-value case. |

## Architecture

- **Entry point:** `src/conductor/cli/graph_cmd.py` (new), registered in `app.py`
  alongside the other top-level commands.
- **Input resolution:** reuse `show`'s path-or-registry-ref logic
  (`registry.resolver.resolve_ref` + `registry.cache.resolve_and_fetch`) so
  `conductor graph qa-bot@registry@1.0.0` works identically to `conductor show`.
- **Parsing:** load via `config/loader.py` → `WorkflowConfig`. No execution, no
  provider instantiation, no network beyond the existing registry fetch.
- **Rendering:** a pure function `render_mermaid(config: WorkflowConfig, depth: int)
  -> str` that walks the config and returns Mermaid `flowchart` text. Kept free of
  I/O so it is trivially unit-testable with golden-file assertions.
- **Output:** stdout by default; `--output FILE` writes to a file.

### Node / edge mapping

- **Agents** → nodes; `entry_point` marked distinctly.
- **Routes** → directed edges; the `when:` expression becomes the edge label, no-`when`
  routes are unlabeled (always-match).
- **`$end`** and **`terminate`** steps → distinct terminal node shapes.
- **Parallel groups** and **for_each** → Mermaid `subgraph` blocks.
- **Step types** (`set`, `script`, `wait`, human gate) → distinct node shapes so the
  graph reads at a glance.
- **`type: workflow` agents** → at `--depth 0`, an opaque node labeled with the
  sub-workflow path; at `--depth >= 1`, a nested `subgraph` with the child's inlined
  topology.

## Scope (milestones the mission planner will refine)

### M1 — Command scaffold + flat render
- New `cli/graph_cmd.py`; registered in `app.py`.
- Resolve workflow (reuse `show`'s ref resolution).
- Emit Mermaid for a single-level workflow: agents as nodes, routes as labeled edges,
  `entry_point` marked, `$end`/`terminate` as terminal nodes.

### M2 — Composite topology
- Parallel groups + for_each rendered as Mermaid `subgraph` blocks.
- Human gates and `set`/`script`/`wait` step types as distinct node shapes.

### M3 — Recursion
- `--depth N` inlines `type: workflow` agents as nested subgraphs.
- Cycle detection (a workflow that transitively references itself).
- Missing/unreadable sub-workflow file → graceful degradation to an opaque node
  labeled with the path (never crash).

### M4 — Output + UX
- `--output FILE`, exit codes (0 ok / 1 load-or-parse error).
- `--help` with examples.
- Node labels escaped for Mermaid safety (quotes, special chars, `when:` expressions).

## Constraints

- **No new dependencies** — Mermaid is plain text.
- **Read-only** — no execution, no checkpoint writes, no network beyond existing
  registry fetch.
- **Deterministic** — same YAML always produces the same Mermaid output (stable node
  ordering) so golden-file tests are reliable.

## Testing & Validation

- `tests/test_cli/test_graph.py` via `typer.testing.CliRunner`.
- Golden-file Mermaid assertions against fixture workflows:
  - simple linear (`examples/simple-qa.yaml`)
  - parallel group (`examples/parallel-research.yaml`)
  - for_each (`examples/for-each-simple.yaml`)
  - nested sub-workflow (`examples/mission/plan.yaml`)
  - registry reference
- Cycle handling (self-referential sub-workflow) and `--depth` truncation.
- `make lint`, `make typecheck`, `make test`.
- Manual: `conductor graph examples/mission/plan.yaml --depth 2`.

## Out of Scope

- ASCII and Graphviz/DOT output formats (deferred; Mermaid only for v1).
- Live/animated graphs or run-state overlay (that is `replay`'s job).
- Editing or validating workflows (that is `validate`'s job).
- Any change to workflow YAML schema.
