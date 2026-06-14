## Area: Core

### VAL-CORE-001: Graph command produces valid Mermaid flowchart on stdout
Running `conductor graph <workflow.yaml>` exits with code 0 and writes a syntactically valid Mermaid `flowchart TD` diagram to stdout. The output begins with `flowchart TD` and contains at least one node definition for the workflow's entry point. All referenced agent, group, and route targets appear as nodes or subgraphs.
Tool: exec
Evidence: exit-code(0), terminal-output(matches /^flowchart TD/)

### VAL-CORE-002: Missing workflow file produces clear error and non-zero exit
Running `conductor graph nonexistent.yaml` exits with code 1 and prints a human-readable error message to stderr indicating the file was not found. No Mermaid output is produced on stdout. The error message is distinct from a YAML parse error or schema validation error — it clearly identifies the root cause as a missing file. The stderr output does NOT contain a Python traceback (`Traceback`).
Tool: exec
Evidence: exit-code(1), terminal-output(stderr contains "not found" or "No such file" or "does not exist"), terminal-output(stderr does NOT contain "Traceback"), terminal-output(stdout does NOT contain "flowchart TD")

### VAL-CORE-003: Invalid YAML or schema produces clear error and non-zero exit
Running `conductor graph` against a file that is not valid workflow YAML (e.g., malformed syntax, missing required top-level keys like `workflow:`, or schema violations like duplicate agent names) exits with code 1 and prints a descriptive error to stderr. The error message identifies the validation problem (e.g., missing field, type mismatch, duplicate name) without exposing a raw Python stack trace. No partial Mermaid output is produced on stdout.
Tool: exec
Evidence: exit-code(1), terminal-output(stderr contains a descriptive validation error), terminal-output(stderr does NOT contain "Traceback"), terminal-output(stdout does NOT contain "flowchart TD")

### VAL-CORE-004: --output flag writes diagram to file instead of stdout
Running `conductor graph <workflow.yaml> --output out.mmd` exits with code 0, produces no Mermaid output on stdout, and creates `out.mmd` containing a valid Mermaid `flowchart TD` diagram identical to what would have been written to stdout. The file begins with `flowchart TD` and contains the same node and edge definitions as the stdout rendering.
Tool: exec
Evidence: exit-code(0), terminal-output(stdout does NOT contain "flowchart TD"), file-exists(out.mmd), file-content(out.mmd matches /^flowchart TD/)

### VAL-CORE-005: --depth 0 renders sub-workflow agents as opaque nodes
When a workflow contains a `type: workflow` agent referencing another workflow file, running `conductor graph <workflow.yaml> --depth 0` renders that agent as a single opaque node (not expanded into a subgraph). The node label includes the agent name but the output contains no Mermaid `subgraph` blocks for the sub-workflow's internal steps. The node has the `workflowStep` class applied.
Tool: exec
Evidence: exit-code(0), terminal-output(contains the sub-workflow agent name as a single node), terminal-output(does NOT contain a `subgraph` block with that agent name), terminal-output(contains "classDef workflowStep")

### VAL-CORE-006: --depth 1 inlines sub-workflows as nested subgraphs
Running `conductor graph <workflow.yaml> --depth 1` (the default) renders `type: workflow` agents as nested Mermaid `subgraph` blocks containing the sub-workflow's internal steps and edges. The subgraph label includes the agent name. Internal agent nodes appear inside the subgraph block.
Tool: exec
Evidence: exit-code(0), terminal-output(contains `subgraph` block whose label includes the sub-workflow agent name), terminal-output(contains agent nodes from the sub-workflow inside that `subgraph` block)

### VAL-CORE-007: Missing sub-workflow file produces error node, not a crash
When `--depth 1` (or higher) encounters a `type: workflow` agent whose referenced file does not exist, the command exits with code 0 and renders an opaque error node in the diagram (labeled with a warning indicator and the missing path). The rest of the workflow diagram is still rendered correctly, with all other nodes and edges present. No stack trace or error output appears on stderr.
Tool: exec
Evidence: exit-code(0), terminal-output(contains an error or warning node with the missing file path), terminal-output(contains other workflow nodes beyond the error node), terminal-output(stderr is empty or contains no "Traceback")

### VAL-CORE-008: Deterministic output — same input always produces identical output
Running `conductor graph <workflow.yaml>` twice against the same file produces byte-for-byte identical stdout output. Node definitions, subgraph blocks, and edge declarations appear in the same order on every run.
Tool: exec
Evidence: exit-code(0) on both runs, terminal-output(run1 == run2 byte-for-byte)

### VAL-CORE-009: --depth out of range produces clear error and non-zero exit
Running `conductor graph <workflow.yaml> --depth -1` or `conductor graph <workflow.yaml> --depth 11` exits with code 1 and prints an error message to stderr indicating the depth value is out of the valid range (0-10). No Mermaid output is produced on stdout.
Tool: exec
Evidence: exit-code(1), terminal-output(stderr contains a message about depth range or invalid depth value), terminal-output(stdout does NOT contain "flowchart TD")

### VAL-CORE-010: --output to non-existent parent directory produces clear error and non-zero exit
Running `conductor graph <workflow.yaml> --output /nonexistent/path/out.mmd` where the parent directory does not exist exits with code 1 and prints an error message to stderr indicating the output path is invalid or the directory does not exist. No Mermaid output is produced on stdout and no partial file is created.
Tool: exec
Evidence: exit-code(1), terminal-output(stderr contains a message about the output path or directory), terminal-output(stdout does NOT contain "flowchart TD"), file-does-not-exist(/nonexistent/path/out.mmd)

## Cross-Area Flows

### VAL-CROSS-001: Linear workflow produces valid Mermaid diagram on stdout
A user runs `conductor graph examples/simple-qa.yaml` and sees a Mermaid `flowchart TD` on stdout. The diagram contains a node for the entry-point agent `answerer` with a `classDef entryPoint` style applied, a node for `$end` with the end-node style, and a solid edge from `answerer` to `$end`. The output can be copied into a Mermaid Live editor and renders without errors. Exit code is 0.
Tool: exec
Evidence: terminal-output(contains "flowchart TD"), terminal-output(contains "answerer"), terminal-output(contains "$end"), terminal-output(contains "classDef entryPoint"), terminal-output(contains "answerer --> $end"), exit-code(0)

### VAL-CROSS-002: Write diagram to file and verify deterministic output
A user runs `conductor graph examples/simple-qa.yaml --output /tmp/test-graph.mmd`. The file at `/tmp/test-graph.mmd` contains the same Mermaid diagram that would appear on stdout, including the header `flowchart TD`, node definitions, edge definitions, and class assignments. Running the command twice produces the same file content (deterministic output). No Mermaid content appears on stdout when `--output` is used.
Tool: exec
Evidence: file-contains(/tmp/test-graph.mmd, "flowchart TD"), file-contains(/tmp/test-graph.mmd, "answerer"), exit-code(0), terminal-output(stdout does NOT contain "flowchart TD")

### VAL-CROSS-003: Complex workflow renders all step types with distinct shapes
A user runs `conductor graph` on a workflow containing agents, script steps, set steps, wait steps, human gates, and terminate steps (both success and failed). Each step type appears with its distinct Mermaid node shape: agents as rectangles (bare `[name]`), script steps as hexagons (`{{name}}`), set steps as stadiums (`([name])`), wait steps as cylinders (`[(name)]`), human gates as rhombuses (`{name}`), terminate-success as a rounded rectangle with `terminateSuccess` class, and terminate-failed as a rounded rectangle with `terminateFailed` class. Parallel groups and for-each groups render as `subgraph` blocks with internal member nodes and edges.
Tool: exec
Evidence: terminal-output(contains a Mermaid hexagon node definition matching `/\w+\{\{/`), terminal-output(contains a Mermaid stadium node definition matching `/\w+\(\[/`), terminal-output(contains a Mermaid cylinder node definition matching `/\w+\[\(/`), terminal-output(contains a Mermaid rhombus node definition matching `/\w+\{/`), terminal-output(contains "subgraph"), terminal-output(contains "classDef terminateSuccess"), terminal-output(contains "classDef terminateFailed"), exit-code(0)

### VAL-CROSS-004: Conditional routes show edge labels and loop-back edges are dotted
A user runs `conductor graph examples/parallel-research.yaml`. The diagram shows a conditional edge from `quality_checker` to `$end` with a `|` label containing the route condition (e.g., `|"quality_score >= 7"|`), and a loop-back edge from `quality_checker` to `planner` rendered as a dotted arrow `-.->` rather than a solid arrow `-->`. Unconditional edges like `planner --> parallel_researchers` have no label.
Tool: exec
Evidence: terminal-output(contains "-->"), terminal-output(contains "-.->"), terminal-output(contains "|"), terminal-output(contains "quality_checker"), terminal-output(contains "planner"), exit-code(0)

### VAL-CROSS-005: Recursive sub-workflow inlining with --depth flag
A user runs `conductor graph examples/mission/plan.yaml --depth 2` on a workflow that references sub-workflow agents (`type: workflow`). The output contains nested Mermaid `subgraph` blocks for sub-workflow files at depth 1 and 2, with their internal agent nodes rendered inside. Sub-workflows beyond depth 2 appear as opaque rounded-rectangle nodes with the `workflowStep` class instead of being inlined. Running with `--depth 0` shows all sub-workflow agents as opaque nodes with no `subgraph` blocks.
Tool: exec
Evidence: terminal-output(contains "subgraph"), terminal-output(contains "classDef workflowStep"), exit-code(0)

### VAL-CROSS-006: Graph of workflow with parallel groups and conditional routes produces structurally valid Mermaid
Running `conductor graph examples/parallel-research.yaml` exits with code 0 and produces a Mermaid `flowchart TD` diagram containing: a `subgraph` block for the `parallel_researchers` group with internal member nodes (`academic_researcher`, `web_researcher`, `technical_researcher`), a labeled conditional edge from `quality_checker` (with `|` syntax for the condition), and a dotted loop-back edge (`-.->`) from `quality_checker` to `planner`. The diagram begins with `flowchart TD`, ends with class definitions, and all edges connect to defined nodes (no dangling references).
Tool: exec
Evidence: exit-code(0), terminal-output(contains "subgraph"), terminal-output(contains "parallel_researchers"), terminal-output(contains "academic_researcher"), terminal-output(contains "web_researcher"), terminal-output(contains "technical_researcher"), terminal-output(contains "quality_checker"), terminal-output(contains "planner"), terminal-output(contains "-.->"), terminal-output(contains "|")