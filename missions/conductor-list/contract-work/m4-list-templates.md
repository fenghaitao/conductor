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
When the built-in template directory (`plugins/conductor-workflow-creator/assets/templates/`) does not exist or is empty, `conductor list templates` exits with code 0 and displays an empty-state message (e.g., "No templates found") instead of crashing or printing a traceback. `conductor list templates --json` emits an empty JSON array `[]`.
Tool: exec
Evidence: terminal-output, exit-code

### VAL-TMPL-006: Non-template files in the template directory are excluded
If a non-YAML file or a YAML file without the expected comment-header format (e.g., a plain config.yaml) is placed in the template directory, `conductor list templates --json` does not include it in the output array. Only files with parsable template metadata (name and description extracted from leading comment lines) appear in results.
Tool: exec
Evidence: terminal-output