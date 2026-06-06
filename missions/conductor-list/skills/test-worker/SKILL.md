---
name: test-worker
description: Write comprehensive pytest tests for CLI commands — output formats, empty states, filtering, edge cases, and deprecation paths — following TDD discipline with CliRunner and Rich output assertions.
---

# Test-Worker

NOTE: Startup and cleanup are handled by worker-base. This skill defines the WORK PROCEDURE.

## Required Skills and Tools

- **pytest** with `CliRunner` from `typer.testing` for CLI invocation and output assertion.
- **`unittest.mock.patch`** for mocking `read_pid_files()`, `CheckpointManager.list_checkpoints()`, event log filesystem I/O, and registry functions.
- **`pytest` fixtures**: `tmp_path` (temp directories with YAML files), `monkeypatch` (override `pid_dir()`, `_conductor_run_dir()`, `CONDUCTOR_HOME`).
- **`yaml` / `json`** for constructing test fixtures (mock YAML workflows, mock PID file JSON, mock event log JSONL).
- **`rich` table assertions** — verify table output via `result.output` string inspection for columns, row counts, dim empty-state messages, and deprecation notices on stderr.

## Work Procedure

### Step 1: Understand Your Feature

Read the mission and architecture documents thoroughly. You need:

- **Mission** (`missions/conductor-list/MISSION.md` or the mission section of the project docs): understand every subcommand (`list`, `list runs`, `list workflows`, `list checkpoints`, `list registries`, `list templates`), the `--json` flag contract, `--recent N` behavior, `--recursive` / `--max-depth` for workflow discovery, `--all` escape hatch, and deprecation notice for `conductor checkpoints`.

- **Architecture** (`missions/conductor-list/ARCHITECTURE.md` or the architecture section): know the data models (`PID Entry`, `Event Log Entry`, `CheckpointData`, `WorkflowFileMeta`, `TemplateMeta`, `RunHistoryEntry`), the module layout (`list_cmd.py` with all commands, `app.py` registration + deprecation wrapper), and integration points (`read_pid_files()`, `CheckpointManager.list_checkpoints()`, `_conductor_run_dir()`, registry functions).

- **Existing test patterns**: study `tests/test_cli/test_stop.py` (PID file mocking, `CliRunner`, `_write_pid` helper, `pid_tmpdir` fixture) and `tests/test_cli/test_registry_commands.py` (subcommand help, empty-state assertions, `CONDUCTOR_HOME` isolation, class-based test organization).

Key edge cases to cover:
- Zero running workflows → dim "No background workflows are running" message.
- Zero recent runs → dim "No recent runs found" message.
- Corrupted JSONL (truncated last line) → graceful skip, not crash.
- Zero YAML files in search path → dim "No workflow files found" message.
- YAML files without `agents:` / `type: workflow` / `runtime:` keys → filtered out (unless `--all`).
- `--recent 0` → treated as no limit, show all.
- `conductor checkpoints` (old command) → still works, prints deprecation notice to stderr.
- `--json` output → valid JSON array, stable field names per data model.

### Step 2: Test First (TDD)

Write failing tests BEFORE the implementation exists. The `list_cmd.py` module won't exist yet, so the tests will fail on import or command resolution — this is expected and confirms the tests are valid.

Create `tests/test_cli/test_list.py` with these test classes:

```
TestListHelp           — `conductor list --help` shows all subcommands
TestListSummary        — `conductor list` (no args) shows counts + hints
TestListRuns           — `list runs` table + JSON, empty state, --recent
TestListWorkflows      — `list workflows` discovery, filtering, --recursive, --all
TestListCheckpoints    — `list checkpoints` table + JSON, empty state, deprecation alias
TestListRegistries     — `list registries` delegation, empty state
TestListTemplates      — `list templates` table + JSON, empty state
TestJsonOutput         — every subcommand with --json produces valid JSON arrays
TestDeprecation        — `conductor checkpoints` prints stderr deprecation + delegates
```

For each test class, write at minimum:
- **Happy path**: normal data, table output has expected columns and rows.
- **Empty state**: no data → dim message, exit code 0.
- **`--json` variant**: same scenario with `--json` → valid JSON array, correct field names.

Use fixtures for isolation:

```python
@pytest.fixture(autouse=True)
def _isolate_conductor_home(monkeypatch, tmp_path):
    """Point CONDUCTOR_HOME to a temp directory."""
    monkeypatch.setenv("CONDUCTOR_HOME", str(tmp_path))

@pytest.fixture()
def pid_tmpdir(tmp_path, monkeypatch):
    """Override pid_dir() to use a temporary directory."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr("conductor.cli.pid.pid_dir", lambda: runs_dir)
    return runs_dir

@pytest.fixture()
def event_log_dir(tmp_path, monkeypatch):
    """Override _conductor_run_dir() to use a temporary directory."""
    run_dir = tmp_path / "events"
    run_dir.mkdir()
    monkeypatch.setattr(
        "conductor.cli.list_cmd._conductor_run_dir",
        lambda: run_dir,
    )
    return run_dir
```

Mocking strategy:
- For `list runs` (running workflows): monkeypatch `read_pid_files` to return lists of 0/1/3 entries with known pid/port/workflow/started_at/run_id values.
- For `list runs --recent`: create temp `*.events.jsonl` files with known `workflow_started` / `workflow_completed` / `workflow_failed` events; also test truncated last lines.
- For `list workflows`: create temp directories with `.yaml` files — some containing `agents:` key (valid workflows), some without (config files). Test `--path`, `--recursive`, `--max-depth`, `--all`.
- For `list checkpoints`: monkeypatch `CheckpointManager.list_checkpoints` to return 0/1/3 `CheckpointData` objects.
- For `list registries`: monkeypatch registry listing functions.
- For `list templates`: point the template discovery path to a temp directory with template YAML files containing comment metadata.

Run the tests to confirm they fail (import errors or `AssertionError`):

```bash
uv run pytest tests/test_cli/test_list.py -v
```

### Step 3: Implement

**You are the test-worker — you do NOT implement `list_cmd.py` or modify `app.py`.** Your job is to write the test file only. The cli-worker owns implementation.

Write the complete test file at `tests/test_cli/test_list.py` with all test classes and cases. Each test must:

1. Use `runner = CliRunner()` (module-level singleton).
2. Invoke via `result = runner.invoke(app, ["list", ...])`.
3. Assert `result.exit_code == 0` (or 1 for error cases).
4. Assert table output content with `assert "column_name" in result.output`.
5. For `--json` tests: `data = json.loads(result.output.strip())`, then assert `isinstance(data, list)` and check field names/types.
6. For empty states: assert `"[dim]"` message in output, exit code 0.
7. For deprecation: `assert "Deprecated" in result.stderr` (CliRunner captures stderr separately from stdout).
8. For error cases (e.g., missing workflow file for `list checkpoints`): assert exit code 1, error message in output.

**Resilience tests** for event log parsing:
- Write a `.events.jsonl` with a truncated last line (no trailing newline after partial JSON) — assert the command doesn't crash and still parses the valid lines.
- Write a `.events.jsonl` with zero valid JSON lines — assert graceful skip.
- Write a `.events.jsonl` with only `workflow_started` (no terminal event) — assert status derives as "running".

**Heuristic filter tests** for workflow discovery:
- YAML with `agents:` at top level → included.
- YAML with `type: workflow` at top level → included.
- YAML with `runtime:` at top level → included.
- YAML with none of these (plain config) → excluded.
- `--all` flag → all YAML files included regardless of content.

### Step 4: Verify

Run tests (will fail until cli-worker implements, but verify they parse correctly):

```bash
uv run pytest tests/test_cli/test_list.py -v
```

Run lint on the test file:

```bash
uv run ruff check tests/test_cli/test_list.py
uv run ruff format --check tests/test_cli/test_list.py
```

Fix all failures before proceeding. Tag flaky or environment-dependent tests with `@pytest.mark.skipif` as appropriate.

### Step 5: Manual Verification

After the cli-worker implements `list_cmd.py` and `app.py` changes:

1. Run `uv run conductor list` — see the summary dashboard with counts.
2. Run `uv run conductor list runs --json` — verify JSON array output with stable field names.
3. Run `uv run conductor list workflows` from the repo root — verify real workflow YAML files are discovered (e.g., `examples/*.yaml`).
4. Run `uv run conductor checkpoints` — verify deprecation notice appears on stderr, functionality unchanged.
5. Run the full test suite: `uv run pytest tests/test_cli/test_list.py -v` — all tests pass.

## Example Handoff

CRITICAL: The Example Handoff section sets the upper bound of expected worker effort. Make it realistic, specific, and thorough. Workers pattern-match against it — the effort level shown here is the effort level you will receive. A thin example produces thin implementations; a thorough example produces thorough ones.

salient_summary: "Wrote comprehensive TDD test suite for conductor list CLI with 40+ test cases covering all subcommands, output formats, empty states, edge cases, and deprecation paths"
what_was_implemented: >
  Created tests/test_cli/test_list.py with 12 test classes:

  TestListHelp (2 tests): verifies `conductor list --help` shows runs/workflows/checkpoints/registries/templates
  subcommands, and that `conductor --help` includes the new `list` group.

  TestListSummary (3 tests): verifies `conductor list` (no subcommand) prints a Rich panel with
  counts for running workflows, recent runs, local workflows, registries, and templates.
  Tests empty-state panel when nothing is configured, and --json emits a summary object.

  TestListRuns (7 tests): mocks read_pid_files() returning 0/1/3 entries — verifies Running Workflows
  table with Port/PID/Workflow/Dashboard columns, dim "No background workflows" when empty,
  correct dashboard URL format (http://127.0.0.1:{port}), --json outputs array of running entries.
  Tests --recent N with mocked event log files (workflow_started + workflow_completed →
  status=completed; workflow_started + workflow_failed → status=failed; workflow_started only →
  status=running). Verifies truncated last lines are skipped without crashing, zero-valid-line
  files are skipped, and --recent 0 shows all entries.

  TestListWorkflows (8 tests): creates temp directories with .yaml files — some containing
  agents:/type:workflow/runtime: keys (valid), some without (config files). Verifies
  Workflow Files table with Name/Path/Agents/Topology columns, heuristic filtering excludes
  config files, --all shows everything, --path starts from different directory,
  --recursive discovers files in subdirectories, --max-depth respects limit,
  --json produces array with name/path/agent_count/has_parallel/has_for_each/has_pipeline/description.

  TestListCheckpoints (5 tests): mocks CheckpointManager.list_checkpoints returning 0/1/3
  CheckpointData objects — verifies Checkpoints table with Workflow/Timestamp/Failed Agent/
  Error Type/File columns, dim "No checkpoints found" when empty, filter by workflow argument,
  filter by nonexistent workflow → exit code 1, --json outputs array.

  TestListRegistries (3 tests): mocks registry listing functions returning 0/2 registries —
  verifies Registries table, "No registries" empty state, and delegation to
  `list registries <name>` for workflow enumeration.

  TestListTemplates (3 tests): creates temp template directory with YAML files containing
  comment metadata — verifies Templates table with Name/Description/Path columns,
  "No templates found" empty state, --json outputs array.

  TestJsonOutput (4 tests): loops over all subcommands with --json, parses output as JSON,
  verifies valid array of objects with stable field names per subcommand data model.
  Tests that --json and non-JSON output both go to stdout (not stderr), and exit code is 0.

  TestDeprecation (3 tests): verifies `conductor checkpoints` still works and prints
  "[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]" to stderr via
  result.stderr assertion. Verifies stdout output is identical between old and new commands.
  Verifies `conductor registry list` is NOT deprecated (no stderr notice).

  All tests use CliRunner, monkeypatch for isolation, and tmp_path for temp files.
  Total: 38 test methods across 12 classes.
what_was_left_undone: ""
verification:
  commands_run:
    - command: "uv run pytest tests/test_cli/test_list.py -v"
      exit_code: 0
      observation: "All 38 tests pass — green bar across all test classes"
    - command: "uv run ruff check tests/test_cli/test_list.py"
      exit_code: 0
      observation: "No lint violations"
    - command: "uv run ruff format --check tests/test_cli/test_list.py"
      exit_code: 0
      observation: "Already well formatted"
  interactive_checks:
    - action: "Run `uv run conductor list` after cli-worker implementation"
      observed: "Summary panel shows running workflows: 0, recent runs: 0, local workflows: 12, registries: 0, templates: 5"
    - action: "Run `uv run conductor list runs --json` with mocked PID files"
      observed: "JSON array with pid/port/workflow/dashboard_url/started_at fields"
    - action: "Run `uv run conductor checkpoints` (deprecated command)"
      observed: "Deprecation notice on stderr, checkpoints table on stdout"
tests_added:
  - file: "tests/test_cli/test_list.py"
    cases:
      - name: "test_list_help_shows_subcommands"
        description: "conductor list --help lists all subcommand names"
      - name: "test_list_summary_shows_counts"
        description: "conductor list prints panel with running/runs/workflows/registries/templates counts"
      - name: "test_list_summary_empty_state"
        description: "All counts zero, dim hints for each subcommand"
      - name: "test_list_runs_empty"
        description: "No running workflows → dim message, exit 0"
      - name: "test_list_runs_single"
        description: "One running workflow → table with correct Port/PID/Workflow/Dashboard columns"
      - name: "test_list_runs_multiple"
        description: "Three running workflows → three rows, correct dashboard URLs"
      - name: "test_list_runs_json"
        description: "--json outputs valid JSON array with pid/port/workflow/dashboard_url/started_at fields"
      - name: "test_list_runs_recent_completed"
        description: "--recent 5 parses event logs, derives status=completed from workflow_completed"
      - name: "test_list_runs_recent_truncated_log"
        description: "Truncated last line in JSONL → parsed without crash, valid lines used"
      - name: "test_list_runs_recent_zero_valid_lines"
        description: "JSONL with no valid JSON → file skipped gracefully"
      - name: "test_list_workflows_heuristic_includes_valid"
        description: "YAML with agents:/type:workflow/runtime: keys → included"
      - name: "test_list_workflows_heuristic_excludes_config"
        description: "YAML without workflow keys → excluded (unless --all)"
      - name: "test_list_workflows_all_flag"
        description: "--all includes config YAML files too"
      - name: "test_list_workflows_recursive"
        description: "--recursive discovers YAML files in subdirectories"
      - name: "test_list_workflows_max_depth"
        description: "--max-depth 1 stops after direct children"
      - name: "test_list_workflows_path"
        description: "--path /other/dir starts search from that directory"
      - name: "test_list_workflows_empty"
        description: "No YAML files in search path → dim message"
      - name: "test_list_workflows_json"
        description: "--json outputs array with name/path/agent_count/topology fields"
      - name: "test_list_checkpoints_table"
        description: "Three checkpoints → table with Workflow/Timestamp/Failed Agent/Error Type/File columns"
      - name: "test_list_checkpoints_empty"
        description: "No checkpoints → dim message, exit 0"
      - name: "test_list_checkpoints_filter_by_workflow"
        description: "Filtered to specific workflow → only matching checkpoints shown"
      - name: "test_list_checkpoints_nonexistent_workflow"
        description: "Nonexistent workflow file → exit 1 with error"
      - name: "test_list_checkpoints_json"
        description: "--json outputs valid array with checkpoint data fields"
      - name: "test_list_registries_table"
        description: "Two registries → table with registry info"
      - name: "test_list_registries_empty"
        description: "No registries → dim message"
      - name: "test_list_registries_by_name"
        description: "list registries <name> shows workflows in that registry"
      - name: "test_list_templates_table"
        description: "Templates from temp dir → table with Name/Description/Path"
      - name: "test_list_templates_empty"
        description: "No template directory → dim message"
      - name: "test_list_templates_json"
        description: "--json outputs array with name/description/path fields"
      - name: "test_json_all_subcommands"
        description: "Every list subcommand with --json produces valid JSON array"
      - name: "test_json_to_stdout"
        description: "JSON output goes to stdout, not stderr"
      - name: "test_deprecation_checkpoints_stderr"
        description: "conductor checkpoints prints deprecation to stderr"
      - name: "test_deprecation_checkpoints_stdout_unchanged"
        description: "Old checkpoints stdout matches list checkpoints stdout"
      - name: "test_no_deprecation_on_registry"
        description: "conductor registry list has no deprecation notice"
return_to_orchestrator: false
discovered_issues: []
skill_name: "test-worker"
skill_feedback: []