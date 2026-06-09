## Area: M1: Core CLI scaffold and `list runs`

### VAL-LRUNS-001: Running workflow table displays all expected columns
Running `conductor list runs` when at least one background workflow is active prints a table to stdout with columns: Port, PID, Workflow, Dashboard URL, and Started. Each row corresponds to exactly one running workflow discovered from PID files.
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
Running `conductor list runs --recent N` scans event log files and prints at most N runs in a table, sorted by start time descending (most recent first). Each row includes the workflow name, run ID, start time, end time (or a running indicator), status, and duration. Runs that match an active PID file entry show status "running" even if their event log lacks a terminal event.
Tool: exec
Evidence: terminal-output(row count ≤ N), terminal-output(contains "completed" or "failed" or "running"), exit-code(0)

### VAL-LRUNS-005: Summary dashboard shows counts with subcommand hints
Running `conductor list` (no subcommand) prints a summary panel to stdout with at minimum: a count of running workflows with a hint like "conductor list runs", a count of recent runs with a hint, and a count of locally discovered workflow files with a hint. All counts are integers (including zero).
Tool: exec
Evidence: terminal-output(contains "running" or "0"), terminal-output(contains "conductor list runs"), terminal-output(contains "conductor list workflows"), exit-code(0)

### VAL-LRUNS-006: Malformed event logs are tolerated without crashing
Running `conductor list runs --recent N` when the event log directory contains a JSONL file with a truncated or invalid last line (e.g., partially written JSON) completes successfully, printing the available runs from valid log entries. The command exits 0 — it does not crash, print a stack trace, or exit non-zero due to a single corrupt log file.
Tool: exec
Evidence: exit-code(0), terminal-output(does NOT contain "Traceback"), terminal-output(does NOT contain "Error")
