## Area: M2: `list workflows` (local discovery)

### VAL-LISTWF-001: Basic listing from current directory
Running `conductor list workflows` in a directory containing one or more YAML files with
top-level `agents:` or `type: workflow` keys displays a table with columns Name, Path,
Agent count, and Topology. Only files matching the workflow heuristic appear; other YAML
files (e.g., CI configs, docker-compose) are excluded. Exit code is 0.
Tool: exec
Evidence: terminal-output (Rich table with correct columns), exit-code (0)

### VAL-LISTWF-002: Empty directory produces graceful message
Running `conductor list workflows` in a directory with no `*.yaml` / `*.yml` files, or
where no YAML files match the workflow heuristic, prints an informative empty-state
message (e.g., "No workflows found") and exits with code 0. The command does NOT crash
or print a Python traceback.
Tool: exec
Evidence: terminal-output (empty-state message, no traceback), exit-code (0)

### VAL-LISTWF-003: Recursive discovery finds workflows in subdirectories
Running `conductor list workflows --recursive` discovers `*.yaml` / `*.yml` files in
subdirectories up to the default max depth (3). Workflow files nested at depth 1, 2,
and 3 appear in the output; files at depth 4 and deeper are excluded. The Path column
shows the relative or absolute path including subdirectories.
Tool: exec
Evidence: terminal-output (workflows from subdirectories present, depth-4+ absent), exit-code (0)

### VAL-LISTWF-004: `--all` flag bypasses heuristic filtering
Running `conductor list workflows --all` shows every `*.yaml` and `*.yml` file in the
search directory, including those that do NOT contain `agents:`, `type: workflow`, or
`runtime:` keys. Non-workflow files are still listed with whatever metadata could be
parsed (e.g., agent count 0, topology empty).
Tool: exec
Evidence: terminal-output (non-workflow YAML files visible), exit-code (0)

### VAL-LISTWF-005: `--json` flag produces valid JSON array
Running `conductor list workflows --json` writes a JSON array to stdout. Each element
is an object with at minimum `name`, `path`, `agent_count`, `has_parallel`,
`has_for_each`, and `has_pipeline` fields. The output can be parsed by `jq` or
`json.loads()` without errors. No Rich table markup or ANSI escapes appear in the
output.
Tool: exec
Evidence: terminal-output (valid JSON array via `| jq .` or `| python3 -m json.tool`), exit-code (0)

### VAL-LISTWF-006: `--path` flag starts search from alternate directory
Running `conductor list workflows --path /tmp/my-workflows` discovers workflow files
in the specified directory instead of the current working directory. The Path column
reflects files under the given root. When the specified path does not exist, the
command prints a clear error message and exits with code 1.
Tool: exec
Evidence: terminal-output (files from --path directory shown), exit-code (0 for valid path, 1 for nonexistent path)

### VAL-LISTWF-007: `--max-depth` limits recursion depth
Running `conductor list workflows --recursive --max-depth 1` discovers files only in
the root directory and immediate subdirectories (depth 1). Files at depth 2 and deeper
are excluded. When combined with `--recursive --max-depth 0`, only the search root
itself is scanned (equivalent to non-recursive behavior).
Tool: exec
Evidence: terminal-output (depth-1 files present, depth-2+ absent), exit-code (0)
