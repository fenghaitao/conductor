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
appropriate types. The JSON is parseable by `jq` or any standard JSON parser.
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