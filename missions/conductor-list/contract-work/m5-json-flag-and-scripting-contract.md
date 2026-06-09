## Area: M5JSON: `--json` flag and scripting contract

### VAL-M5JSON-001: `--json` flag emits valid JSON array to stdout
When `conductor list runs --json` is invoked, stdout contains a syntactically valid JSON array (parsable by `jq` or `python -m json.tool`) and stderr contains no JSON output (only diagnostic messages if any).
Tool: exec
Evidence: terminal-output, exit-code

### VAL-M5JSON-002: Exit code is 0 on successful JSON output
When a `list` subcommand with `--json` completes without encountering missing files, unreadable event logs, or other runtime errors, the process exits with code 0.
Tool: exec
Evidence: exit-code

### VAL-M5JSON-003: Exit code is 1 when JSON output cannot be produced due to error
When `conductor list runs --recent 5 --json` is pointed at a nonexistent or inaccessible event log directory, or when `conductor list checkpoints --json` targets a missing workflow file, the process exits with code 1.
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