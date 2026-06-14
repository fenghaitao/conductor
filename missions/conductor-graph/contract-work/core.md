## Area: Core

### VAL-CORE-001: Graph command produces valid Mermaid flowchart on stdout
Running `conductor graph <workflow.yaml>` exits with code 0 and writes a syntactically valid Mermaid `flowchart TD` diagram to stdout. The output begins with `flowchart TD` and contains at least one node definition for the workflow's entry point. All referenced agent, group, and route targets appear as nodes or subgraphs.
Tool: exec
Evidence: exit-code(0), terminal-output(matches /^flowchart TD/)

### VAL-CORE-002: Missing workflow file produces clear error and non-zero exit
Running `conductor graph nonexistent.yaml` exits with code 1 and prints a human-readable error message to stderr indicating the file was not found. No Mermaid output is produced on stdout.
Tool: exec
Evidence: exit-code(1), terminal-output(stderr contains "not found" or "No such file")

### VAL-CORE-003: Invalid YAML produces clear error and non-zero exit
Running `conductor graph` against a file that is not valid workflow YAML (e.g., malformed syntax or missing required fields) exits with code 1 and prints a descriptive error to stderr. No partial Mermaid output is produced on stdout.
Tool: exec
Evidence: exit-code(1), terminal-output(stderr contains error details)

### VAL-CORE-004: --output flag writes diagram to file instead of stdout
Running `conductor graph <workflow.yaml> --output out.mmd` exits with code 0, produces no Mermaid output on stdout, and creates `out.mmd` containing a valid Mermaid `flowchart TD` diagram identical to what would have been written to stdout.
Tool: exec
Evidence: exit-code(0), terminal-output(stdout empty or metadata only), file-exists(out.mmd), file-content(out.mmd matches /^flowchart TD/)

### VAL-CORE-005: --depth 0 renders sub-workflow agents as opaque nodes
When a workflow contains a `type: workflow` agent referencing another workflow file, running `conductor graph <workflow.yaml> --depth 0` renders that agent as a single opaque node (not expanded into a subgraph). The node label includes the agent name but not the sub-workflow's internal steps.
Tool: exec
Evidence: exit-code(0), terminal-output(contains sub-workflow agent name as a single node, no nested subgraph for that agent)

### VAL-CORE-006: --depth 1 inlines sub-workflows as nested subgraphs
Running `conductor graph <workflow.yaml> --depth 1` (the default) renders `type: workflow` agents as nested Mermaid `subgraph` blocks containing the sub-workflow's internal steps and edges. The subgraph label includes the agent name.
Tool: exec
Evidence: exit-code(0), terminal-output(contains `subgraph` block with the sub-workflow agent name)

### VAL-CORE-007: Missing sub-workflow file produces error node, not a crash
When `--depth 1` (or higher) encounters a `type: workflow` agent whose referenced file does not exist, the command exits with code 0 and renders an opaque error node in the diagram (labeled with a warning indicator and the missing path). The rest of the workflow diagram is still rendered correctly.
Tool: exec
Evidence: exit-code(0), terminal-output(contains error node with missing path, rest of diagram intact)

### VAL-CORE-008: Deterministic output — same input always produces identical output
Running `conductor graph <workflow.yaml>` twice against the same file produces byte-for-byte identical stdout output. Node definitions, subgraph blocks, and edge declarations appear in the same order on every run.
Tool: exec
Evidence: exit-code(0) on both runs, terminal-output(run1 == run2 byte-for-byte)