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
When no user-provided template directories are configured (only built-in templates exist), `conductor list templates` still prints a table listing the built-in templates and exits with code 0 — it does not error or print an empty table.
Tool: exec
Evidence: exit-code = 0; terminal-output is a table with ≥ 1 data row

### VAL-M4LIST-007: Invalid --json combined with --help exits cleanly
Running `conductor list templates --json --help` shows the help text (not JSON) and exits with code 0. Typer's built-in help flag takes precedence over the JSON flag.
Tool: exec
Evidence: terminal-output contains "--json" in help text; exit-code = 0