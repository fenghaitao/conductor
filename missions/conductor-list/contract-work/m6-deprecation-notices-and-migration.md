## Area: M6: Deprecation notices and migration

### VAL-M6DEPR-001: Old `checkpoints` command prints deprecation notice to stderr
Running `conductor checkpoints` (without arguments) writes a deprecation message containing the text `conductor list checkpoints` to stderr, while still emitting the expected checkpoint table (or empty-state message) to stdout and exiting with code 0.
Tool: exec
Evidence: terminal-output (stderr must contain `[dim]Deprecated` and `conductor list checkpoints`; stdout must contain the checkpoint listing table or empty-state message), exit-code (must be 0)

### VAL-M6DEPR-002: Old `checkpoints` command with workflow argument prints deprecation notice
Running `conductor checkpoints examples/simple-qa.yaml` writes the same deprecation notice to stderr, filters checkpoints to the given workflow file, and prints matching results to stdout.
Tool: exec
Evidence: terminal-output (stderr must contain deprecation notice; stdout must contain filtered checkpoint table or empty-state for no matches), exit-code (0)

### VAL-M6DEPR-003: Old `checkpoints --json` still works with deprecation notice on stderr
Running `conductor checkpoints --json` writes the deprecation notice to stderr and a valid JSON array of checkpoint objects to stdout. The JSON output matches the same schema produced by `conductor list checkpoints --json`.
Tool: exec
Evidence: terminal-output (stderr contains deprecation notice; stdout is a parseable JSON array whose structure matches the new command), exit-code (0)

### VAL-M6DEPR-004: New `list checkpoints` does NOT print deprecation notice
Running `conductor list checkpoints` (without arguments) writes checkpoint output to stdout and does NOT write any deprecation-related message to stderr.
Tool: exec
Evidence: terminal-output (stderr must NOT contain `Deprecated` or any deprecation language), exit-code (0)

### VAL-M6DEPR-005: New and old checkpoints commands produce identical stdout
Running `conductor checkpoints` and `conductor list checkpoints` back-to-back (without `--json`) produces the same table output on stdout. The only difference is that the old command also writes a deprecation notice to stderr.
Tool: exec
Evidence: terminal-output (stdout from both commands must match line-for-line after stripping ANSI escape codes; stderr from the new command must be empty except for the deprecation notice on the old command)

### VAL-M6DEPR-006: `registry list` is NOT deprecated
Running `conductor registry list` does NOT write any deprecation notice to stderr and behaves exactly as before — same output, same exit code, no new warnings.
Tool: exec
Evidence: terminal-output (stderr must NOT contain `Deprecated` or `use 'conductor list`), exit-code (0)

### VAL-M6DEPR-007: `conductor --help` shows `list` group and hides deprecated `checkpoints`
Running `conductor --help` includes the `list` command group in the top-level commands listing. The old `checkpoints` command is either absent from the top-level listing (hidden) or shown with a deprecation indicator.
Tool: exec
Evidence: terminal-output (output must contain `list` as a top-level command group; `checkpoints` must NOT appear as a visible top-level command, or if visible must include deprecation language)

### VAL-M6DEPR-008: Old `checkpoints` remains functional (no crash, correct data)
Running `conductor checkpoints` against a workflow that has saved checkpoints (e.g., after a failed run) lists those checkpoints with correct timestamps, workflow paths, and failure summaries — identical to the data shown by `conductor list checkpoints`.
Tool: exec
Evidence: terminal-output (checkpoint count matches between old and new commands; timestamps, error types, and agent names are identical between both outputs), exit-code (0)