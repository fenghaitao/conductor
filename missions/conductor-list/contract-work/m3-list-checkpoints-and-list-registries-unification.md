## Area: M3: `list checkpoints` and `list registries` (unification)

### VAL-M3LIST-001: Running `conductor list checkpoints` with no arguments displays all saved checkpoints in a table
When the user invokes `conductor list checkpoints` and at least one checkpoint exists on disk, a Rich-styled table is printed to stdout with columns for version, workflow path, created timestamp, failure error type, and the agent name at failure.
Tool: exec
Evidence: terminal-output contains a table with column headers including "Version", "Workflow", "Created", "Error", and "Agent"; exit-code is 0.

### VAL-M3LIST-002: Running `conductor list checkpoints --json` emits a valid JSON array
When the user invokes `conductor list checkpoints --json` and checkpoints exist, stdout contains a JSON array where each element is an object with fields `version`, `workflow_path`, `workflow_hash`, `created_at`, `failure`, `current_agent`, `run_id`, and `file_path`. The output is valid JSON parseable by `jq` or any JSON parser.
Tool: exec
Evidence: exit-code is 0; piping stdout through `jq '.'` succeeds with no parse errors; the root JSON value is an array.

### VAL-M3LIST-003: Running `conductor list checkpoints <workflow-path>` filters results to that workflow only
When the user invokes `conductor list checkpoints path/to/specific.yaml` and checkpoints exist for multiple workflows, only checkpoints whose `workflow_path` matches `path/to/specific.yaml` appear in the output.
Tool: exec
Evidence: terminal-output table rows all reference the given workflow path; exit-code is 0.

### VAL-M3LIST-004: Running the deprecated `conductor checkpoints` command prints a deprecation notice to stderr and still produces the checkpoint table
When the user invokes the old top-level `conductor checkpoints` command, a dimmed deprecation message reading "Deprecated: use 'conductor list checkpoints' instead" is printed to stderr, and the same checkpoint table is printed to stdout as `conductor list checkpoints` would produce.
Tool: exec
Evidence: stderr contains the deprecation notice string; stdout contains the checkpoint table; exit-code is 0.

### VAL-M3LIST-005: Running `conductor list registries` with no arguments lists all configured registries in a table
When the user invokes `conductor list registries` and at least one registry is configured in `~/.conductor/registries.json`, a table is printed to stdout with columns for registry name, URL, and type.
Tool: exec
Evidence: terminal-output contains a table with registry entries; exit-code is 0.

### VAL-M3LIST-006: Running `conductor list registries <name>` lists workflows published in that registry
When the user invokes `conductor list registries <name>` and the named registry exists in the local configuration, a table of workflows available in that registry is printed to stdout with columns for workflow name and description.
Tool: exec
Evidence: terminal-output contains a table with workflow entries from the named registry; exit-code is 0.

### VAL-M3LIST-007: Running `conductor list registries <nonexistent-name>` with an unknown registry name prints a clear error to stderr
When the user invokes `conductor list registries unknown-registry` and no registry with that name is configured, a clear error message is printed to stderr indicating the registry was not found, and the command exits with a non-zero status.
Tool: exec
Evidence: stderr contains an error message mentioning the unknown registry name; exit-code is 1.

### VAL-M3LIST-008: Running `conductor list checkpoints` when no checkpoints exist prints an informative empty-state message
When the user invokes `conductor list checkpoints` and the checkpoint directory is empty or does not exist, a message indicating no checkpoints are available is printed to stdout, and the command exits successfully.
Tool: exec
Evidence: terminal-output contains a message like "No checkpoints found" or similar empty-state text; exit-code is 0; no error output on stderr.