## Area: M1: Core CLI scaffold and `list runs`

### VAL-LRUNS-001: Running workflow table displays all expected columns
Running `conductor list runs` when at least one background workflow is active prints a table to stdout with columns: Port, PID, Workflow, Dashboard URL, and Started. Each row corresponds to exactly one running workflow.
Tool: exec
Evidence: terminal-output(contains "Port"), terminal-output(contains "PID"), terminal-output(contains "Workflow"), terminal-output(contains "Dashboard"), terminal-output(contains "Started"), terminal-output(contains "http://127.0.0.1:")

### VAL-LRUNS-002: Empty state message when no workflows are running
Running `conductor list runs` when no background workflows are active prints a dim, human-readable message to stdout indicating that nothing is running — without erroring or printing a table header row.
Tool: exec
Evidence: terminal-output(contains a dim/no-runs message), terminal-output(does NOT contain "Port"), exit-code(0)

### VAL-LRUNS-003: JSON output produces a valid, parsable JSON array
Running `conductor list runs --json` prints a JSON array to stdout. When workflows are running, each array element contains the keys `pid`, `port`, `workflow`, `dashboard_url`, and `started_at`. When nothing is running, the output is an empty JSON array `[]`. The command still exits 0 in both cases.
Tool: exec
Evidence: terminal-output(is valid JSON array), terminal-output(elements contain "pid" or array is empty), exit-code(0)

### VAL-LRUNS-004: Recent run history is sorted and limited to N entries
Running `conductor list runs --recent N` prints at most N runs in a table, sorted by start time descending (most recent first). Each row includes the workflow name, run ID, start time, end time (or a running indicator), status, and duration. Runs that are currently active show status "running" even if no terminal status has been recorded yet.
Tool: exec
Evidence: terminal-output(row count ≤ N), terminal-output(contains "completed" or "failed" or "running"), exit-code(0)

### VAL-LRUNS-005: Summary dashboard shows counts with subcommand hints
Running `conductor list` (no subcommand) prints a summary panel to stdout with at minimum: a count of running workflows with a hint like "conductor list runs", a count of recent runs with a hint, and a count of locally discovered workflow files with a hint. All counts are integers (including zero).
Tool: exec
Evidence: terminal-output(contains "running" or "0"), terminal-output(contains "conductor list runs"), terminal-output(contains "conductor list workflows"), exit-code(0)

### VAL-LRUNS-006: Malformed run data is tolerated without crashing
Running `conductor list runs --recent N` when some stored run history is malformed or incomplete completes successfully, printing the available runs from valid data. The command exits 0 — it does not crash, print a stack trace, or exit non-zero due to a single corrupt record.
Tool: exec
Evidence: exit-code(0), terminal-output(does NOT contain "Traceback"), terminal-output(does NOT contain "Error")


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


## Area: M3: `list checkpoints` and `list registries` (unification)

### VAL-M3LIST-001: Running `conductor list checkpoints` with no arguments displays all saved checkpoints in a table
When the user invokes `conductor list checkpoints` and at least one checkpoint has been saved, a Rich-styled table is printed to stdout with columns for version, workflow path, created timestamp, failure error type, and the agent name at failure.
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
When the user invokes `conductor list registries` and at least one registry is configured, a table is printed to stdout with columns for registry name, URL, and type.
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
When the user invokes `conductor list checkpoints` and no checkpoints have been saved, a message indicating no checkpoints are available is printed to stdout, and the command exits successfully.
Tool: exec
Evidence: terminal-output contains a message like "No checkpoints found" or similar empty-state text; exit-code is 0; no error output on stderr.

## Area: M4: `list templates`

### VAL-M4LIST-001: Table output lists built-in templates
Running `conductor list templates` prints a Rich table to stdout containing at least 3 rows, each with a non-empty Name, a non-empty Description, and an absolute Path column. The command exits with code 0.
Tool: exec
Evidence: terminal-output contains a table with columns "Name", "Description", "Path"; exit-code = 0

### VAL-M4LIST-002: JSON output is a valid JSON array of objects
Running `conductor list templates --json` prints a JSON array to stdout where each element is an object with keys `name`, `description`, and `path`, all of type string. The array has at least 3 elements. The command exits with code 0.
Tool: exec
Evidence: terminal-output parses as valid JSON array with `jq '. | length'` returning ≥ 3; `jq '.[0] | keys'` returns `["name","description","path"]`

### VAL-M4LIST-003: Template names and descriptions are non-empty strings
Every template in `conductor list templates --json` has a non-empty `name` string and a non-empty `description` string. No template has a blank or null name or description.
Tool: exec
Evidence: `jq '.[] | select(.name == "" or .name == null)'` returns empty; `jq '.[] | select(.description == "" or .description == null)'` returns empty

### VAL-M4LIST-004: Template paths are absolute and point to existing files
Every template in `conductor list templates --json` has a `path` that is an absolute path starting with `/` and pointing to a `.yaml` or `.yml` file that exists on disk. Substituting any returned path into `ls <path>` succeeds.
Tool: exec
Evidence: `jq -r '.[].path' | while read p; do [ -f "$p" ]; done` exits 0; all paths start with `/`

### VAL-M4LIST-005: Table and JSON outputs are consistent
Running `conductor list templates` (table) and `conductor list templates --json` reports the same number of templates, and the names in the table rows match the names in the JSON array (same set, same order).
Tool: exec
Evidence: count of table data rows equals `jq '. | length'` from JSON output; `jq -r '.[].name'` from JSON matches names extracted from table output

### VAL-M4LIST-006: Command succeeds when no user templates exist
When no user-provided templates are available (only built-in templates exist), `conductor list templates` still prints a table listing the built-in templates and exits with code 0 — it does not error or print an empty table.
Tool: exec
Evidence: exit-code = 0; terminal-output is a table with ≥ 1 data row

### VAL-M4LIST-007: Invalid --json combined with --help exits cleanly
Running `conductor list templates --json --help` shows the help text (not JSON) and exits with code 0. Typer's built-in help flag takes precedence over the JSON flag.
Tool: exec
Evidence: terminal-output contains "--json" in help text; exit-code = 0

## Area: M5JSON: `--json` flag and scripting contract

### VAL-M5JSON-001: `--json` flag emits valid JSON array to stdout
When `conductor list runs --json` is invoked, stdout contains a syntactically valid JSON array (parsable by `jq` or `python -m json.tool`) and stderr contains no JSON output (only diagnostic messages if any).
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M5JSON-002: Exit code is 0 on successful JSON output
When a `list` subcommand with `--json` completes without encountering missing files, unreadable data, or other runtime errors, the process exits with code 0.
Tool: exec
Evidence: exit-code

### VAL-M5JSON-003: Exit code is 1 when JSON output cannot be produced due to error
When `conductor list runs --recent 5 --json` is pointed at unavailable or inaccessible run history data, or when `conductor list checkpoints --json` targets a missing workflow file, the process exits with code 1.
Tool: exec
Evidence: exit-code

### VAL-M5JSON-004: Error messages are written to stderr, keeping stdout parseable
When a `--json` invocation fails, the error message appears on stderr only. Stdout is either empty or contains a valid (possibly empty) JSON array — never a plain-text error message interleaved with JSON.
Tool: exec
Evidence: terminal-output

### VAL-M5JSON-005: Empty result set produces an empty JSON array
When a `list` subcommand with `--json` finds zero results (e.g., `conductor list runs --json` with no running workflows, or `conductor list workflows --json` in a directory with no workflow YAML files), stdout contains exactly `[]` (an empty JSON array), not `null`, `{}`, or a plain-text "No results" message.
Tool: exec
Evidence: terminal-output

### VAL-M5JSON-006: JSON output schema is stable across invocations
Running the same `list` subcommand with `--json` twice against unchanged data produces JSON arrays with the same top-level keys in each object (field names and types are identical). Adding a new workflow YAML file or a new running workflow does not change the shape of existing entries — only appends new objects with the same schema.
Tool: exec
Evidence: terminal-output

### VAL-M5JSON-007: `--json` output can be piped to downstream tools
A pipe such as `conductor list runs --json | jq '.[0].port'` or `conductor list workflows --json | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"` executes without error when results exist, confirming the output is a single, self-contained JSON document with no extra framing or interactive prompts.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M5JSON-008: `--json` flag is rejected when combined with unrecognized arguments
When `conductor list runs --json --unknown-flag` is invoked, the command exits with a non-zero exit code and prints a usage/error message to stderr — it does not silently ignore the unknown flag and produce JSON output.
Tool: exec
Evidence: exit-code, terminal-output

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

## Cross-Area Flows

### VAL-CROSS-001: Discover running workflows from summary to detail to dashboard
A user runs `conductor list` and sees a count of running workflows with a hint to run `conductor list runs`. They run `conductor list runs` and see a table of running background workflows showing Port, PID, Workflow name, Dashboard URL, and Started time. They open one of the Dashboard URLs in a browser and see the live workflow graph with agent states.
Tool: exec
Evidence: terminal-output(`conductor list` shows count ≥ 0 and hint), terminal-output(`conductor list runs` shows table with Port/PID/Workflow columns or empty-state message), exit-code(0)

### VAL-CROSS-002: Find a workflow file, run it, and see it appear in recent history
A user runs `conductor list workflows` and sees a table of discovered workflow YAML files with Name, Path, Agent count, and Topology tags. They pick one, run it with `conductor run <path>`, wait for completion, then run `conductor list runs --recent 5`. The recently completed run appears with status "completed" and a non-null duration.
Tool: exec
Evidence: terminal-output(`conductor list workflows` shows filtered YAML files), terminal-output(`conductor list runs --recent 5` includes the just-completed run with status=completed), exit-code(0)

### VAL-CROSS-003: Background workflow lifecycle — list, stop, verify gone
A user starts a workflow in background mode with `conductor run <path> --web-bg`. They run `conductor list runs` and see the new entry with a PID and Dashboard URL. They stop it with `conductor stop --port <port>`. Running `conductor list runs` again shows the workflow is no longer in the running table (though it may appear in `--recent` history with status=failed due to the stop).
Tool: exec
Evidence: terminal-output(`conductor list runs` after start shows the entry), terminal-output(`conductor list runs` after stop omits the entry from running table), exit-code(0)

### VAL-CROSS-004: Checkpoint discovery and resume after failure
A user runs `conductor list checkpoints` and sees a list of saved checkpoints with workflow path, failure reason, and timestamp. They resume the latest one with `conductor resume <path>`. The resumed run completes, and `conductor list runs --recent 1` shows the resumed run with status "completed" and the same run_id as in the checkpoint listing.
Tool: exec
Evidence: terminal-output(`conductor list checkpoints` shows at least one entry with file_path), terminal-output(`conductor list runs --recent 1` after resume shows completed status), exit-code(0)

### VAL-CROSS-005: JSON export for CI scripting — runs and workflows
A CI script runs `conductor list runs --json` and receives a valid JSON array of run history objects. Each object has `workflow`, `run_id`, `started_at`, `status`, and `duration_seconds` fields. The script also runs `conductor list workflows --json --recursive` and receives a JSON array of workflow file metadata with `name`, `path`, `agent_count`, and topology tags. Both commands exit 0 and the JSON can be piped to `jq` for filtering.
Tool: exec
Evidence: terminal-output(`conductor list runs --json | jq '.'` is valid JSON array), terminal-output(`conductor list workflows --json | jq '.[0].name'` extracts a field), exit-code(0) for both

### VAL-CROSS-006: Template discovery to workflow instantiation
A user runs `conductor list templates` and sees a table of available workflow templates with Name, Description, and Path. They pick a template and run `conductor init --template <template-name> <output-path>`. Running `conductor list workflows --path <output-dir>` shows the newly created workflow file with the expected agent count and topology from the template.
Tool: exec
Evidence: terminal-output(`conductor list templates` shows template names and paths), terminal-output(`conductor list workflows --path <output-dir>` includes the created file with correct metadata), exit-code(0)