---
name: cli-worker
description: Implements Typer CLI subcommands with Rich tables, filesystem discovery, and JSON output. Use when adding new CLI command groups or subcommands to Conductor.
---

# Cli-Worker

NOTE: Startup and cleanup are handled by worker-base. This skill defines the WORK PROCEDURE.

## Required Skills and Tools

- **filesystem tools**: `pathlib.Path.glob` / `rglob`, `json.loads`, `yaml.safe_load` for reading PID files, event logs, checkpoints, and workflow YAML.
- **bash**: Run `uv run conductor <command>`, `uv run pytest`, `uv run ty check`, `uv run ruff`.
- **Typer**: Define command groups with `typer.Typer()`, commands with `@app.command()`, options with `Annotated[type, typer.Option(...)]`, arguments with `Annotated[type, typer.Argument(...)]`.
- **Rich**: `rich.table.Table` for formatted output to `output_console` (stdout). `rich.console.Console(stderr=True)` for errors and deprecation notices.
- **CliRunner**: `typer.testing.CliRunner` for CLI tests — invoke commands by string list, assert `result.exit_code` and `result.output`.
- **pytest fixtures**: `monkeypatch` for env vars and module attribute overrides, `tmp_path` for temp directories, `patch` from `unittest.mock` for external calls.

## Work Procedure

### Step 1: Understand Your Feature
Read your feature description and fulfills assertions carefully.
Read relevant sections of architecture.md to understand:
- Which existing modules to import from (`cli/pid.py`, `engine/checkpoint.py`, `cli/registry.py`, `config/loader.py`).
- Which single new file owns all implementation (`src/conductor/cli/list_cmd.py`).
- Which existing file gets a one-line registration change (`src/conductor/cli/app.py`).
- The data models for each subcommand (PID entries, event log entries, checkpoint data, workflow file metadata, template metadata, run history entries).

### Step 2: Test First (TDD)
Write failing tests before writing implementation code.
Create `tests/test_cli/test_list.py` with these test classes at minimum:
- **TestListHelp** — `conductor list --help` shows all subcommands (runs, workflows, checkpoints, registries, templates).
- **TestListSummary** — `conductor list` (no subcommand) prints a summary panel with counts.
- **TestListRuns** — Mock `read_pid_files()` to return 0, 1, and multiple entries; assert table rows and empty-state message.
- **TestListRunsRecent** — Create temp event log files with valid/invalid JSON; assert `--recent N` truncation, status derivation (completed/failed/running), cross-referencing with PID files.
- **TestListRunsJson** — Assert `--json` emits a valid JSON array with correct schema fields.
- **TestListWorkflows** — Create temp directories with `.yaml` files (some valid workflows with `agents:`, some non-workflow configs); assert heuristic filtering and `--all` behavior. Test `--recursive` and `--max-depth`.
- **TestListWorkflowsJson** — Assert `--json` output schema.
- **TestListCheckpoints** — Verify output matches existing `conductor checkpoints` behavior. Assert `--json` mode.
- **TestListRegistries** — Verify delegation to existing `conductor registry list` commands.
- **TestListTemplates** — Assert template discovery from `plugins/conductor-workflow-creator/assets/templates/`. Assert `--json` mode.
- **TestDeprecationNotice** — `conductor checkpoints` still works but emits `[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]` to stderr.
- **TestEmptyStates** — Every subcommand handles the empty case gracefully (no running workflows, no YAML files, no checkpoints, no registries, no templates).

Run: `uv run pytest tests/test_cli/test_list.py -v` — confirm ALL tests fail (red).

### Step 3: Implement
Create **one new file**: `src/conductor/cli/list_cmd.py` containing:

1. **Typer app**: `list_app = typer.Typer(name="list", help="Discover workflows, runs, checkpoints, and more.", no_args_is_help=False)`

2. **Callback** (`list_summary`): Prints a Rich Panel or table with counts for running workflows, recent runs, local workflow files, registries, and templates. Each count includes a dim hint for the full subcommand.

3. **`list_runs` command**:
   - `--recent N: int = 0` — show last N completed/failed runs from event logs.
   - `--json / --no-json: bool = False` — emit JSON array instead of table.
   - Reuse `conductor.cli.pid.read_pid_files()` for running workflows.
   - For `--recent`, glob `$TMPDIR/conductor/conductor-*.events.jsonl`, parse first and last valid JSON lines per file.
   - Cross-reference `run_id` in PID files to mark running workflows correctly.
   - Tolerate truncated last lines (parse line-by-line, skip invalid JSON with debug log).
   - Table columns: Port, PID, Workflow (stem), Dashboard URL (`http://127.0.0.1:{port}`), Started. For `--recent`: Workflow, Run ID, Started, Ended, Status, Duration.

4. **`list_workflows` command**:
   - `--path DIR: Path = cwd` — search root.
   - `--recursive / --no-recursive: bool = False` — walk subdirectories.
   - `--max-depth N: int = 3` — recursion limit.
   - `--all / --no-all: bool = False` — skip heuristic filtering.
   - Walk for `*.yaml` / `*.yml` files. Read first 2 KB, string-search for `agents:`, `type: workflow`, or `runtime:`.
   - If matched, parse with `yaml.safe_load` and extract: name, agent count, topology tags (has_parallel, has_for_each, has_pipeline), description.
   - Table columns: Name, Path, Agents, Topology.

5. **`list_checkpoints` command**:
   - `[WORKFLOW]` optional argument — filter by workflow path.
   - `--json / --no-json: bool = False`.
   - Delegates to `CheckpointManager.list_checkpoints(workflow_path)`.
   - Extract shared `_list_checkpoints_impl(workflow: Path | None, json_output: bool)` so the deprecated `checkpoints` command in `app.py` can reuse it.

6. **`list_registries` command**:
   - `[NAME]` optional argument.
   - Delegates to `conductor.cli.registry._list_all_registries()` or `conductor.cli.registry._list_registry_workflows(name)`.
   - No `--json` needed (registry commands already support their own output).

7. **`list_templates` command**:
   - `--json / --no-json: bool = False`.
   - Discover from `plugins/conductor-workflow-creator/assets/templates/`.
   - Parse YAML frontmatter comments (first 2 lines after `#`): line 1 = name, line 2 = description.
   - Table columns: Name, Description, Path.

8. **JSON helpers**: Each subcommand with `--json` has a corresponding `_build_*_json()` function that returns a list of dicts. Use `output_console.print_json(json.dumps(data))`.

9. **Defensive I/O**: Every filesystem read is wrapped in try/except. Corrupted PID files, truncated event logs, unparseable YAML, and missing directories produce debug logs — never crashes.

Modify **one existing file**: `src/conductor/cli/app.py`:
- Add `from conductor.cli.list_cmd import list_app` after the registry import.
- Add `app.add_typer(list_app)` after `app.add_typer(registry_app)`.
- Modify the existing `checkpoints` command: add `hidden=True` to the decorator, print `[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]` to stderr via `console.print()`, then delegate to `from conductor.cli.list_cmd import _list_checkpoints_impl; _list_checkpoints_impl(workflow)`.

### Step 4: Verify
Run scoped commands first, then full suite:

```bash
# Tests — scoped to the new test file
uv run pytest tests/test_cli/test_list.py -v

# Typecheck — scoped to the new module and modified app.py
uv run ty check src/conductor/cli/list_cmd.py src/conductor/cli/app.py

# Lint
uv run ruff check src tests
uv run ruff format --check src tests
```

Fix ALL failures before proceeding. If a test or type error reveals a missing import or API mismatch, fix the implementation — do not weaken the test.

Then run the full suite to confirm no regressions:

```bash
make check    # lint + typecheck (full)
make test     # all tests (excludes install_scripts)
```

### Step 5: Manual Verification
Exercise every new command path:

```bash
# Summary dashboard
uv run conductor list

# Help
uv run conductor list --help

# Runs (empty — no background workflows)
uv run conductor list runs
uv run conductor list runs --json

# Runs with recent history (requires prior runs with event logs)
uv run conductor list runs --recent 5
uv run conductor list runs --recent 5 --json

# Workflows — discover examples/
uv run conductor list workflows --path examples/
uv run conductor list workflows --path examples/ --recursive
uv run conductor list workflows --path examples/ --json

# Checkpoints — same as old command
uv run conductor list checkpoints
uv run conductor list checkpoints --json

# Deprecated alias still works
uv run conductor checkpoints 2>&1 | head -5

# Registries
uv run conductor list registries
uv run conductor list registries official  # if configured

# Templates
uv run conductor list templates
uv run conductor list templates --json
```

Verify each command exits 0. Verify `--json` output is valid JSON via `| python -m json.tool`. Verify the deprecation notice appears on stderr for `conductor checkpoints`. Verify `conductor list --help` lists all subcommands.

## Example Handoff

salient_summary: "Implemented `conductor list` command group with runs, workflows, checkpoints, registries, and templates subcommands"
what_was_implemented: >
  Created `src/conductor/cli/list_cmd.py` with a `list_app` Typer group containing
  five subcommands: `list` (summary callback), `list runs` (running workflows +
  `--recent N` history), `list workflows` (local YAML discovery with heuristic
  filtering), `list checkpoints` (drop-in replacement for `conductor checkpoints`),
  `list registries` (delegates to existing registry commands), and `list templates`
  (built-in template discovery). Every subcommand supports `--json` for
  machine-readable output. Event log parsing is defensive — truncated last lines
  are skipped, corrupted PID files are cleaned up silently. YAML heuristic filter
  reads only the first 2 KB and checks for `agents:`, `type: workflow`, or
  `runtime:` keys. Registered `list_app` in `app.py` and wrapped the old
  `checkpoints` command with a deprecation notice to stderr and delegation to the
  shared `_list_checkpoints_impl()` function. All output goes to stdout
  (`output_console`) — the primary result, not diagnostic noise.
what_was_left_undone: ""
verification:
  commands_run:
    - command: "uv run pytest tests/test_cli/test_list.py -v"
      exit_code: 0
      observation: "All tests pass — summary, runs, runs --recent, workflows, checkpoints, registries, templates, deprecation notice, empty states, JSON schema"
    - command: "uv run ty check src/conductor/cli/list_cmd.py src/conductor/cli/app.py"
      exit_code: 0
      observation: "No type errors in new or modified files"
    - command: "uv run ruff check src tests && uv run ruff format --check src tests"
      exit_code: 0
      observation: "No lint or format violations"
    - command: "make test"
      exit_code: 0
      observation: "Full test suite passes — no regressions in existing commands"
    - command: "make check"
      exit_code: 0
      observation: "Full lint + typecheck passes"
  interactive_checks:
    - action: "uv run conductor list"
      observed: "Summary panel with counts for running workflows, recent runs, local workflows, registries, templates. Each count has a dim hint for the full subcommand."
    - action: "uv run conductor list runs --json | python -m json.tool"
      observed: "Valid JSON array. Empty when no background workflows running."
    - action: "uv run conductor list workflows --path examples/ --recursive"
      observed: "Rich table with Name, Path, Agents, Topology columns. Only actual workflow YAML files shown (config files filtered out)."
    - action: "uv run conductor checkpoints 2>&1"
      observed: "Deprecation notice on stderr followed by checkpoint table on stdout. Same output as `conductor list checkpoints`."
    - action: "uv run conductor list templates"
      observed: "Table with pipeline, loop, fan-out templates and their descriptions."
tests_added:
  - file: "tests/test_cli/test_list.py"
    cases:
      - name: "test_list_help_shows_subcommands"
        description: "conductor list --help lists runs, workflows, checkpoints, registries, templates"
      - name: "test_list_summary_shows_counts"
        description: "conductor list prints summary panel with counts and hints"
      - name: "test_list_runs_empty"
        description: "conductor list runs shows empty-state message when no background workflows"
      - name: "test_list_runs_with_entries"
        description: "Mocked read_pid_files returns entries; table has correct rows and columns"
      - name: "test_list_runs_json"
        description: "--json emits valid JSON array matching RunEntry schema"
      - name: "test_list_runs_recent_from_event_logs"
        description: "--recent N scans event log files, derives status, truncates to N"
      - name: "test_list_runs_recent_tolerates_corrupted_logs"
        description: "Truncated/invalid JSON lines are skipped, valid lines still parsed"
      - name: "test_list_workflows_heuristic_filter"
        description: "Non-workflow YAML files (no agents:/type: workflow/runtime:) are excluded"
      - name: "test_list_workflows_all_flag"
        description: "--all shows all YAML files regardless of content"
      - name: "test_list_workflows_recursive_depth"
        description: "--recursive respects --max-depth, finds nested workflow files"
      - name: "test_list_workflows_json"
        description: "--json emits valid JSON array with name, path, agent_count, topology fields"
      - name: "test_list_checkpoints_matches_old_command"
        description: "conductor list checkpoints output matches conductor checkpoints output"
      - name: "test_list_checkpoints_json"
        description: "--json emits valid JSON array of checkpoint data"
      - name: "test_deprecation_notice_on_stderr"
        description: "conductor checkpoints prints deprecation notice to stderr, delegates to list checkpoints"
      - name: "test_list_registries_delegates"
        description: "conductor list registries calls existing _list_all_registries"
      - name: "test_list_registries_with_name"
        description: "conductor list registries <name> calls existing _list_registry_workflows"
      - name: "test_list_templates_discovers_builtins"
        description: "conductor list templates finds pipeline, loop, fan-out from plugins/"
      - name: "test_list_templates_json"
        description: "--json emits valid JSON array with name, description, path"
      - name: "test_empty_states_all_subcommands"
        description: "Every subcommand handles empty state gracefully with dim message, no crash"
return_to_orchestrator: false
discovered_issues: []
skill_name: "cli-worker"
skill_feedback: []