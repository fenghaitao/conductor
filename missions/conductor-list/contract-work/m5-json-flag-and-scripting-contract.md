## Area: M5: `--json` flag and scripting contract

### VAL-M5JSON-001: `--json` produces valid JSON array on stdout with exit code 0
Running any `conductor list` subcommand with `--json` emits a syntactically valid JSON array to stdout and exits with code 0 when the underlying data source is readable and accessible.
Tool: exec
Evidence: exit-code=0, terminal-output contains valid JSON array (parsable by `jq` or `python -m json.tool`)

### VAL-M5JSON-002: `--json` emits NOTHING to stderr on success
When a `conductor list` subcommand with `--json` completes successfully, nothing is written to stderr — the entire JSON payload lands on stdout, making the output safe for pipes and shell substitution without noise contamination.
Tool: exec
Evidence: terminal-output, console-errors is empty

### VAL-M5JSON-003: Errors cause exit code 1 with message on stderr, not a best-effort JSON on stdout
When a `--json` invocation encounters a hard error (e.g., the event-log directory is unreadable or a required file is missing), the command exits with code 1, prints an error message to stderr, and does NOT emit a partial or empty JSON array to stdout.
Tool: exec
Evidence: exit-code=1, console-errors contains error text, terminal-output is empty or contains no valid JSON

### VAL-M5JSON-004: Empty result sets produce a valid empty JSON array `[]`
When a `--json` invocation completes successfully but finds no data (e.g., `conductor list runs --json` when no workflows are running and no recent logs exist), stdout still receives a valid, parsable empty JSON array `[]` — not `null`, not `{}`, not a string like `"No results"`.
Tool: exec
Evidence: exit-code=0, terminal-output is exactly `[]` (or whitespace-equivalent), console-errors is empty

### VAL-M5JSON-005: Schema stability — repeated invocations produce objects with identical top-level keys
Running the same `--json` subcommand twice (under the same filesystem state) produces JSON arrays whose objects have the same set of top-level keys in the same order. Keys are never omitted or renamed based on optional data presence (missing optional values appear as `null`).
Tool: exec
Evidence: terminal-output — comparing `jq '.[0] | keys'` across two invocations yields identical output

### VAL-M5JSON-006: `--json` on `list runs --recent` tolerates partially-written event logs
When event-log JSONL files contain a truncated final line (e.g., a crash mid-write), `conductor list runs --recent --json` silently skips the malformed line, still produces a valid JSON array from the preceding valid lines, and exits with code 0 rather than crashing or printing a stack trace.
Tool: exec
Evidence: exit-code=0, terminal-output is valid JSON array, console-errors is empty

### VAL-M5JSON-007: `list` summary callback with `--json` is rejected or falls back gracefully
If the top-level `conductor list --json` summary dashboard is invoked with `--json`, the command either rejects it with a clear error (exit 1, message to stderr) because the summary is a display artifact, or emits a structured summary object (not a Rich-rendered string) as a valid JSON object. The behavior is documented and deterministic.
Tool: exec
Evidence: exit-code consistent with documented contract; if rejected, console-errors contains explanation; if accepted, terminal-output is valid JSON