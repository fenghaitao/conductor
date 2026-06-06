## Area: M3: `list checkpoints` and `list registries` (unification)

### VAL-M3LIST-001: List checkpoints displays Rich table with checkpoint data
Running `conductor list checkpoints` when at least one checkpoint exists prints a formatted Rich table to stdout containing columns for workflow, checkpoint timestamp, failure error type, and the agent that was current at the time of failure.
Tool: exec
Evidence: terminal-output — stdout contains a Rich-rendered table with recognizable column headers (e.g., Workflow, Created, Error, Agent).

### VAL-M3LIST-002: List checkpoints `--json` outputs valid JSON array
Running `conductor list checkpoints --json` when at least one checkpoint exists prints a valid JSON array of objects to stdout. Each object contains at minimum `workflow_path`, `created_at`, `failure`, and `current_agent` fields. The command exits with code 0.
Tool: exec
Evidence: exit-code = 0; terminal-output — stdout is parseable as a JSON array where every element is an object with the required keys.

### VAL-M3LIST-003: List checkpoints with workflow argument filters results
Running `conductor list checkpoints <path-to-workflow.yaml>` displays only checkpoints whose `workflow_path` matches the given argument. Checkpoints from other workflow files are excluded from output.
Tool: exec
Evidence: terminal-output — every row in the table (or every object in `--json` output) has a workflow path matching the supplied argument.

### VAL-M3LIST-004: List checkpoints with no checkpoints shows empty-state message
Running `conductor list checkpoints` when no checkpoints exist on disk prints a user-friendly message indicating no checkpoints were found (e.g., "No checkpoints found") and exits with code 0 rather than an error.
Tool: exec
Evidence: exit-code = 0; terminal-output — stdout contains a message conveying "no checkpoints" without a traceback or error styling.

### VAL-M3LIST-005: List registries displays configured registries
Running `conductor list registries` when at least one registry is configured prints a table or list to stdout showing each registry's name and source URL. The output is the same as running `conductor registry list`.
Tool: exec
Evidence: terminal-output — stdout of `conductor list registries` matches stdout of `conductor registry list` when run with the same configuration.

### VAL-M3LIST-006: List registries with name argument shows workflows in that registry
Running `conductor list registries <name>` where `<name>` is a configured registry prints a table or list of workflows published in that registry. The output matches `conductor registry list <name>`.
Tool: exec
Evidence: terminal-output — stdout of `conductor list registries <name>` matches stdout of `conductor registry list <name>` for the same registry name.

### VAL-M3LIST-007: List registries with no configured registries handles gracefully
Running `conductor list registries` when no registries are configured prints a message indicating no registries are available (e.g., "No registries configured") and exits with code 0 rather than an error.
Tool: exec
Evidence: exit-code = 0; terminal-output — stdout contains a message conveying "no registries" without a traceback or error styling.

### VAL-M3LIST-008: Deprecated `conductor checkpoints` command still works with notice
Running the old `conductor checkpoints` command (without the `list` prefix) still executes the checkpoint listing, but prints a deprecation notice to stderr advising the user to use `conductor list checkpoints` instead. The stdout output is identical to `conductor list checkpoints`.
Tool: exec
Evidence: exit-code = 0; terminal-output — stderr contains the deprecation notice; stdout matches the output of `conductor list checkpoints` with the same arguments.
