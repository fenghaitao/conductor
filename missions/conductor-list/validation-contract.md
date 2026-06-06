## Area: M1: Core CLI scaffold and `list runs`

### VAL-M1CORE-001: Summary dashboard shows counts and subcommand hints
Running `conductor list` without arguments prints a summary panel to stdout containing at minimum: a count of running workflows (e.g., "Running: N"), a count of recent runs (e.g., "Recent runs: N"), and for each count a hint pointing to the corresponding subcommand (e.g., "conductor list runs" or "conductor list runs --recent"). The command exits with code 0.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-002: Running workflows table displays all columns when workflows are active
When at least one background workflow is running, `conductor list runs` prints a Rich table to stdout with columns: Port, PID, Workflow, Dashboard URL, and Started. Each running workflow occupies one row. The Port column contains an integer, the PID column contains an integer, the Workflow column contains a recognizable workflow file stem, the Dashboard URL column contains a valid `http://127.0.0.1:<port>` URL, and the Started column contains an ISO-8601 timestamp. The command exits with code 0.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-003: Empty state message when no workflows are running
When no background workflows are running, `conductor list runs` prints a single dim/informational message to stdout indicating that no workflows are currently running — for example, "No running workflows" or equivalent. No table is printed. The command exits with code 0, not an error.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-004: JSON mode outputs a valid JSON array of running workflows
Running `conductor list runs --json` outputs a valid JSON array to stdout. When workflows are running, each array element is an object containing at minimum `port` (number), `pid` (number), `workflow` (string), and `started_at` (ISO-8601 string) fields. When no workflows are running, the output is an empty JSON array `[]`. The command exits with code 0 in both cases.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-005: Recent runs displays completed and failed runs from run history
Running `conductor list runs --recent N` (where N is a positive integer) prints a table of at most N recent runs, sorted by start time most-recent-first, derived from the run history that `conductor` persists across invocations. Each row shows at minimum: workflow name, run identifier, start time, end time (or "running"), status (one of "completed", "failed", or "running"), and duration. A run that completed successfully shows status "completed"; a run that terminated with an error shows status "failed"; an in-progress run shows status "running". The command exits with code 0.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-006: Recent runs tolerates corrupted or truncated run history data
When the persisted run history contains malformed or truncated data (simulated by creating a run-history record with zero valid entries, or a record whose last entry is incomplete), `conductor list runs --recent N` completes successfully and skips the unparseable record or unparseable entries without crashing. The command still reports valid runs from other history records, exits with code 0, and does not print a stack trace to stdout or stderr.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-007: Active runs are identified correctly in recent history
When a run is still in progress (as confirmed by its presence in `conductor list runs`), `conductor list runs --recent N` displays that run with status "running" and no end time. When a run is no longer active (not shown in `conductor list runs` and no dashboard is reachable at its port) but no terminal status was recorded, the run is displayed with a status indicating it is not running (e.g., "unknown" or "interrupted"), not as "running".
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-008: Summary dashboard works correctly when nothing exists
Running `conductor list` on a system with no running workflows, no run history, no local workflow files, no configured registries, and no templates still exits with code 0 and prints a summary panel showing zero counts for each category (e.g., "Running: 0", "Recent runs: 0") along with the corresponding subcommand hints. No error message is printed to stdout or stderr.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-009: Recent runs rejects invalid count argument
Running `conductor list runs --recent 0` or `conductor list runs --recent -1` prints a clear error message to stderr indicating the count must be a positive integer, exits with code 1, and does not print a table or JSON array to stdout.
Tool: exec
Evidence: terminal-output, exit-code

## Area: M2: `list workflows` (local discovery)

### VAL-M2LIST-001: Lists workflow files in the current directory (non-recursive by default)
Running `conductor list workflows` in a directory containing `.yaml` files with recognized workflow keys
lists those files in a table with Name, Path, Agent count, and Topology columns. Files lacking `agents:`,
`type: workflow`, or `runtime:` top-level keys are excluded. The command exits with code 0 and prints
only the table (no deprecation notices, warnings, or diagnostics).
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M2LIST-002: Recursive discovery with `--recursive` respects `--max-depth`
Running `conductor list workflows --recursive --max-depth 2` in a directory tree discovers workflow
YAML files at depth 1 and 2 but does not inspect files at depth 3 or deeper. Without `--max-depth`,
the default depth limit of 3 is applied. With `--max-depth 0`, only the current directory is searched
(equivalent to non-recursive).
Tool: exec
Evidence: terminal-output

### VAL-M2LIST-003: `--path` flag starts search from a different directory
Running `conductor list workflows --path /some/other/dir` discovers workflow files under that
directory instead of the current working directory. The output paths in the table are absolute or
relative to the specified `--path`, not to the original `cwd`. The command succeeds even when the
current working directory contains no workflow files.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M2LIST-004: `--json` flag emits a valid JSON array
Running `conductor list workflows --json` writes exactly one JSON array to stdout with no
surrounding text, banners, or diagnostic output. Each array element contains `name`, `path`,
`agent_count`, `has_parallel`, `has_for_each`, `has_pipeline`, and `description` fields with
appropriate types. The JSON is parseable by any standard JSON parser.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M2LIST-005: Heuristic filtering excludes non-workflow YAML files
Creating a YAML file without `agents:`, `type: workflow`, or `runtime:` keys (e.g., a
`docker-compose.yaml` with `services:` only) and running `conductor list workflows` does not list
that file. A YAML file containing any of those three keys IS listed. The heuristic scan reads at
most the first 2 KB of each file, so a YAML file with workflow keys buried after 2 KB of comments
or preamble is NOT listed (a known limitation, not a bug).
Tool: exec
Evidence: terminal-output

### VAL-M2LIST-006: `--all` flag bypasses heuristic filtering
Running `conductor list workflows --all` lists every `*.yaml` and `*.yml` file regardless of
content — even files that would be excluded by the heuristic filter (e.g., `docker-compose.yaml`,
`ci-config.yaml`). The output table includes all YAML files; agent counts and topology tags may show
as 0/"unknown" for non-workflow files.
Tool: exec
Evidence: terminal-output

### VAL-M2LIST-007: Graceful handling of empty or non-existent directories
Running `conductor list workflows --path /tmp/nonexistent-dir` where the directory does not exist
prints a clear error message to stderr and exits with code 1 (not a Python traceback). Running
`conductor list workflows` in an empty directory (or one with no YAML files at all) prints a dim
informational message to stdout (e.g., "No workflow files found.") and exits with code 0.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M2LIST-008: YAML files with `.yaml` and `.yml` extensions are both discovered
Creating a valid workflow file named `my-workflow.yml` (lowercase `.yml`) alongside
`another-workflow.yaml` (lowercase `.yaml`) and running `conductor list workflows` lists both files.
Files with uppercase extensions (`.YAML`, `.YML`) are also discovered.
Tool: exec
Evidence: terminal-output

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

### VAL-M3LIST-009: List registries with unknown registry name shows clear error
Running `conductor list registries <nonexistent-name>` where `<nonexistent-name>` is not a configured registry prints a clear error message to stderr (e.g., "Registry 'nonexistent-name' not found") and exits with code 1. No table or JSON is printed to stdout.
Tool: exec
Evidence: exit-code = 1; terminal-output — stderr contains the registry name in the error message; stdout is empty or contains no table/JSON.

## Area: M4: `list templates`

### VAL-TMPL-001: Table output lists all built-in templates
Running `conductor list templates` displays a Rich table containing at least 3 template entries — pipeline, fan-out, and loop — each with a non-empty Name, Description, and Path column. The table header row is visible and the command exits within 2 seconds.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-TMPL-002: JSON output returns a valid array of template objects
Running `conductor list templates --json` emits a JSON array to stdout. Each element is an object containing at minimum the fields `name` (non-empty string), `description` (non-empty string), and `path` (non-empty string pointing to an existing `.yaml` or `.yml` file). The JSON is valid and the array length matches the number of table rows from the default (non-JSON) invocation.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-TMPL-003: Template names and descriptions match their YAML comment headers
For each template entry in `conductor list templates --json`, the `name` field contains the descriptive title from the first comment line of the template file (e.g., "Pipeline template: Sequential stages with conditional routing"), and the `description` field contains the text from the second non-empty comment line (e.g., "Use when: Work flows through ordered stages"). Neither field is simply the filename stem.
Tool: exec
Evidence: terminal-output

### VAL-TMPL-004: Exit code is 0 when templates are successfully listed
`conductor list templates` and `conductor list templates --json` both exit with code 0 when templates are discovered and displayed. No errors or warnings are written to stderr during normal operation.
Tool: exec
Evidence: exit-code

### VAL-TMPL-005: Command degrades gracefully when no template directory exists
When the built-in template directory does not exist or is empty, `conductor list templates` exits with code 0 and displays an empty-state message (e.g., "No templates found") instead of crashing or printing a traceback. `conductor list templates --json` emits an empty JSON array `[]`.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-TMPL-006: Non-template files in the template directory are excluded
If a non-YAML file or a YAML file without the expected comment-header format (e.g., a plain config.yaml) is placed in the template directory, `conductor list templates --json` does not include it in the output array. Only files with parsable template metadata (name and description extracted from leading comment lines) appear in results.
Tool: exec
Evidence: terminal-output

## Area: M5: `--json` flag and scripting contract

### VAL-M5JSON-001: `--json` produces valid JSON array on stdout with exit code 0
Running any `conductor list` subcommand with `--json` emits a syntactically valid JSON array to stdout and exits with code 0 when the underlying data source is readable and accessible.
Tool: exec
Evidence: exit-code=0, terminal-output contains valid JSON array (parsable by a standard JSON parser)

### VAL-M5JSON-002: `--json` emits NOTHING to stderr on success
When a `conductor list` subcommand with `--json` completes successfully, nothing is written to stderr — the entire JSON payload lands on stdout, making the output safe for pipes and shell substitution without noise contamination.
Tool: exec
Evidence: terminal-output, console-errors is empty

### VAL-M5JSON-003: Errors cause exit code 1 with message on stderr, not a best-effort JSON on stdout
When a `--json` invocation encounters a hard error (e.g., the run-history directory is unreadable or a required file is missing), the command exits with code 1, prints an error message to stderr, and does NOT emit a partial or empty JSON array to stdout.
Tool: exec
Evidence: exit-code=1, console-errors contains error text, terminal-output is empty or contains no valid JSON

### VAL-M5JSON-004: Empty result sets produce a valid empty JSON array `[]`
When a `--json` invocation completes successfully but finds no data (e.g., `conductor list runs --json` when no workflows are running and no run history exists), stdout still receives a valid, parsable empty JSON array `[]` — not `null`, not `{}`, not a string like `"No results"`.
Tool: exec
Evidence: exit-code=0, terminal-output is exactly `[]` (or whitespace-equivalent), console-errors is empty

### VAL-M5JSON-005: Schema stability — repeated invocations produce objects with identical top-level keys
Running the same `--json` subcommand twice (under the same filesystem state) produces JSON arrays whose objects have the same set of top-level keys in the same order. Keys are never omitted or renamed based on optional data presence (missing optional values appear as `null`).
Tool: exec
Evidence: terminal-output — extracting the keys of the first array element from two consecutive invocations yields identical output.

### VAL-M5JSON-006: `--json` on `list runs --recent` tolerates partially-written run history
When the persisted run history contains a truncated final record (simulating a crash during a previous write), `conductor list runs --recent --json` silently skips the malformed record, still produces a valid JSON array from the preceding valid records, and exits with code 0 rather than crashing or printing a stack trace.
Tool: exec
Evidence: exit-code=0, terminal-output is valid JSON array, console-errors is empty

### VAL-M5JSON-007: `list` summary with `--json` is rejected with a clear error
Running `conductor list --json` (the top-level summary dashboard with the `--json` flag) exits with code 1, prints a clear error message to stderr explaining that `--json` is not supported on the summary command and directing the user to use a specific subcommand (e.g., `conductor list runs --json`), and does NOT emit the summary panel to stdout as a JSON string or object.
Tool: exec
Evidence: exit-code=1, console-errors contains guidance referencing a subcommand, terminal-output contains no valid JSON

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
Evidence: terminal-output (stdout parses as valid JSON array; stderr contains deprecation message), exit-code (0)

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

## Cross-Area Flows

### VAL-CROSS-001: Summary dashboard reflects all discovery areas
A user runs `conductor list` with no subcommand. The summary panel shows
a count of running workflows, a count of recent runs (last 24h), a count
of local workflow files found in the current directory, the number of
configured registries, and the number of available templates. Each count
is accompanied by a hint pointing to the corresponding subcommand. When
zero running workflows exist, the summary shows "0 running" rather than
omitting the line. When zero recent runs exist, the line still appears
with a zero count. The summary never crashes regardless of which
discovery sources are unavailable — missing directories, absent PID
files, or empty registries all produce zero counts, not errors.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-CROSS-002: Running workflow appears in both live list and recent history
A user starts a background workflow with `conductor run workflow.yaml --web-bg`.
They immediately run `conductor list runs` and see the workflow in the
running table with a port, PID, workflow name, dashboard URL, and start
time. After the workflow completes (or fails), the user runs `conductor list runs --recent 1`.
The completed workflow now appears in the recent runs table with its
final status (completed or failed), end time, and duration. The same run
does not appear in both the running and recent tables simultaneously —
a run transitions from the running table to the recent table once it
has finished executing.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-CROSS-003: Template discovered then surfaced in local workflow listing
A user runs `conductor list templates` and sees a table of built-in
templates with name, description, and file path. They pick one (e.g.,
"pipeline") and run `conductor init my-workflow --template pipeline`.
The command creates `my-workflow.yaml` in the current directory. When
the user runs `conductor list workflows`, the newly created file
appears in the local workflow table with its name, path, agent count,
and topology tags (pipeline). Another YAML file in the same directory
that lacks `agents:` or `type: workflow` keys (e.g., a Docker Compose
file) does not appear in the workflow listing. With `--all`, both files
appear.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-CROSS-004: Checkpoint listed then workflow resumed and shown as running
A user runs a workflow that fails partway through, generating an
on-failure checkpoint. They run `conductor list checkpoints` and see
the saved checkpoint in the table with the workflow path, failure
reason, agent name, and timestamp. They then run
`conductor resume workflow.yaml` to restart from that checkpoint.
While the resumed workflow is running, `conductor list runs` shows it
as an active entry with a port, PID, and dashboard URL. After the
resumed workflow completes, `conductor list runs --recent 1` shows it
in the recent history with status "completed". The checkpoint remains
listed after the resume completes — checkpoints are never deleted by
the `list` commands.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-CROSS-005: Registry listing consistent across list and registry commands
A user runs `conductor list registries` and sees a table of configured
registries. They pick one by name and run `conductor list registries
<name>` to see all published workflows in that registry, displayed as a
table with workflow names and descriptions. The same output is produced
by running `conductor registry list <name>` — the two commands are
functionally equivalent for this operation. The legacy `conductor
registry list` (without the `list` prefix) produces identical output
without any deprecation notice, since it belongs to the `registry`
subcommand group. The `list registries` and `registry list` commands
share the same underlying data and produce identical table columns and
ordering.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-CROSS-006: JSON scripting contract consistent across all subcommands
A user or CI script runs every `list` subcommand with the `--json` flag:
`conductor list runs --json`, `conductor list workflows --json`,
`conductor list checkpoints --json`, `conductor list registries --json`,
`conductor list templates --json`. Each command writes a valid JSON array
to stdout (not stderr) and exits with code 0. The JSON arrays are empty
(`[]`) when no results exist — never `null`, never an object, never
absent. Each object in the array has a stable set of keys matching the
subcommand's documented output schema. Non-JSON output (progress messages,
deprecation notices, warnings) goes to stderr, leaving stdout clean for
pipe consumers. The summary command (`conductor list`) does not support
`--json` and exits with code 1 when `--json` is passed, since its output
is inherently a formatted panel.
Tool: exec
Evidence: terminal-output, exit-code