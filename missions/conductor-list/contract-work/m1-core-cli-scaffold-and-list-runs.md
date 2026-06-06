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
When no background workflows are running (no PID files exist), `conductor list runs` prints a single dim/informational message to stdout indicating that no workflows are currently running — for example, "No running workflows" or equivalent. No table is printed. The command exits with code 0, not an error.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-004: JSON mode outputs a valid JSON array of running workflows
Running `conductor list runs --json` outputs a valid JSON array to stdout. When workflows are running, each array element is an object containing at minimum `port` (number), `pid` (number), `workflow` (string), and `started_at` (ISO-8601 string) fields. When no workflows are running, the output is an empty JSON array `[]`. The command exits with code 0 in both cases.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-005: Recent runs displays completed and failed runs from event logs
Running `conductor list runs --recent N` (where N is a positive integer) prints a table of at most N recent runs, sorted by start time most-recent-first, derived from `conductor-*.events.jsonl` files in the conductor run directory. Each row shows at minimum: workflow name, run identifier, start time, end time (or "running"), status (one of "completed", "failed", or "running"), and duration. A run whose event log ends with a `workflow_completed` event shows status "completed"; a run ending with `workflow_failed` shows status "failed"; a run with no terminal event (and no matching active PID entry) shows an appropriate status. The command exits with code 0.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-006: Recent runs tolerates corrupted or truncated event log files
When the conductor run directory contains malformed or truncated `.events.jsonl` files (e.g., a file with zero valid JSON lines, or a file whose last line is incomplete JSON), `conductor list runs --recent N` completes successfully and skips the unparseable file or unparseable lines without crashing. The command still reports valid runs from other event log files, exits with code 0, and does not print a stack trace to stdout or stderr.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-007: Active runs are identified correctly even without terminal events
When an event log file lacks a terminal event (no `workflow_completed` or `workflow_failed` line) but its run identifier matches an entry in the active PID files, `conductor list runs --recent N` displays that run with status "running" and no end time. When an event log file lacks a terminal event and its run identifier does NOT match any active PID file, the run is displayed with a status indicating it is not running (e.g., "unknown" or "interrupted"), not as "running".
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M1CORE-008: Summary dashboard works correctly when nothing exists
Running `conductor list` on a system with no running workflows, no event logs, no local workflow files, no configured registries, and no templates still exits with code 0 and prints a summary panel showing zero counts for each category (e.g., "Running: 0", "Recent runs: 0") along with the corresponding subcommand hints. No error message is printed to stdout or stderr.
Tool: exec
Evidence: terminal-output, exit-code