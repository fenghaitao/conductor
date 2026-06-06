## Area: M6: Deprecation notices and migration

### VAL-M6DEPR-001: Old checkpoints command prints deprecation notice to stderr
Running `conductor checkpoints` prints a deprecation message to stderr indicating the user should use `conductor list checkpoints` instead, while still emitting the normal checkpoint table to stdout.
Tool: exec
Evidence: terminal-output (stderr contains "Deprecated" or "deprecated" and references "conductor list checkpoints"), exit-code (0)

### VAL-M6DEPR-002: Old checkpoints command still produces correct checkpoint data
Running `conductor checkpoints workflow.yaml` (with an existing checkpointed workflow) outputs the same checkpoint listing data as `conductor list checkpoints workflow.yaml`, differing only in the deprecation notice on stderr.
Tool: exec
Evidence: terminal-output (stdout of old command matches stdout of new command after stripping timestamps/paths that may differ between runs)

### VAL-M6DEPR-003: Registry list command emits no deprecation notice
Running `conductor registry list` (with at least one configured registry) prints registry information to stdout and emits no deprecation warning to stderr — the command belongs to the `registry` subcommand group and is not deprecated.
Tool: exec
Evidence: terminal-output (stderr is empty or contains no "Deprecated" / "deprecated" text), exit-code (0)

### VAL-M6DEPR-004: Old checkpoints command with --json emits deprecation notice and valid JSON
Running `conductor checkpoints --json` prints the deprecation notice to stderr and a valid JSON array of checkpoint objects to stdout. The stdout content is parseable as JSON and contains no deprecation text.
Tool: exec
Evidence: terminal-output (stdout parses as valid JSON array via `jq` or equivalent; stderr contains deprecation message), exit-code (0)

### VAL-M6DEPR-005: New list checkpoints command emits no deprecation notice
Running `conductor list checkpoints` produces the checkpoint listing without any deprecation warning on stderr — the new canonical command is clean.
Tool: exec
Evidence: terminal-output (stderr is empty or contains no "Deprecated" text), exit-code (0)

### VAL-M6DEPR-006: Old checkpoints command appears hidden in top-level help
Running `conductor --help` does not list `checkpoints` as a visible top-level command — it is hidden from the default help output to guide users toward `conductor list checkpoints`. The `list` group and its `checkpoints` subcommand are visible instead.
Tool: exec
Evidence: terminal-output (help text lacks a visible `checkpoints` top-level entry; `list` group is shown)

### VAL-M6DEPR-007: Old checkpoints command still works with --help flag
Running `conductor checkpoints --help` still displays usage information for the deprecated command, including its argument description and options, so users who discover it through muscle memory can understand what it does and how to migrate.
Tool: exec
Evidence: terminal-output (help text includes argument description and lists `[WORKFLOW]` positional argument), exit-code (0)