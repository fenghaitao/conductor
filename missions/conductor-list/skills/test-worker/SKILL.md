---
name: test-worker
description: Writes pytest tests for CLI subcommands — table and JSON output, empty states, filtering, deprecation notices, and JSON schema stability.
---

# Test-Worker

NOTE: Startup and cleanup are handled by worker-base. This skill defines the WORK PROCEDURE.

## Required Skills and Tools

- **bash**: Run `uv run pytest`, `make lint`, `make typecheck`, and `uv run conductor list ...` for manual verification.
- **view / grep / glob**: Read source files (`src/conductor/cli/list_cmd.py`, `src/conductor/cli/pid.py`, `src/conductor/engine/checkpoint.py`, `src/conductor/cli/app.py`) and test fixtures.
- **edit**: Write test code in `tests/test_cli/test_list.py`.
- **create**: Create the test file if it does not already exist (parent directory `tests/test_cli/` must already exist).
- **Rich `CliRunner`**: Use `typer.testing.CliRunner` for all CLI integration tests. `CliRunner` invokes the Typer app in-process — no subprocess, no port binding, no network.
- **pytest fixtures**: `tmp_path` for temp directories and files; `monkeypatch` for replacing functions like `read_pid_files` and `CheckpointManager.list_checkpoints`; `unittest.mock.patch` for finer-grained mocking of `_conductor_run_dir`, `glob`, and `yaml.safe_load`.

## Work Procedure

### Step 1: Understand Your Feature
Read the mission (`missions/conductor-list/mission.md`) and architecture (`missions/conductor-list/architecture.md`) carefully. Pay attention to:

- **Subcommands under test**: `conductor list` (summary), `conductor list runs`, `conductor list runs --recent N`, `conductor list workflows`, `conductor list workflows --recursive`, `conductor list workflows --all`, `conductor list checkpoints`, `conductor list registries`, `conductor list templates`.
- **Output modes**: Rich table (default, stdout) and `--json` (stdout, JSON array). Every subcommand must be tested in both modes.
- **Empty states**: When nothing is running, no workflows found, no checkpoints, no recent runs — each subcommand must print a dim message (no crash, exit code 0).
- **Flags**: `--recent N`, `--path <dir>`, `--recursive / --max-depth`, `--all`, `--json`.
- **Deprecation**: `conductor checkpoints` (top-level, not under `list`) must print a `[dim]Deprecated: ...[/dim]` notice to stderr and then produce the same output as `conductor list checkpoints`.
- **Error tolerance**: Corrupted event log lines are skipped (not crashed). Missing directories produce empty results.

Read the list command source (`src/conductor/cli/list_cmd.py`) to understand the exact function signatures, import paths, and Rich table column names you will be asserting against.

### Step 2: Test First (TDD)
Create `tests/test_cli/test_list.py` if it doesn't exist. Write failing tests before the implementation exists:

1. **Summary command**: `conductor list` (no args) prints a Rich panel with counts.
2. **Runs table**: `conductor list runs` with 0, 1, and 3 mocked PID entries.
3. **Runs JSON**: `conductor list runs --json` emits valid JSON array.
4. **Recent runs**: `conductor list runs --recent 5` scans mocked event log files.
5. **Workflows table**: `conductor list workflows` discovers YAML files with heuristic filtering.
6. **Workflows --all**: `conductor list workflows --all` includes non-workflow YAML.
7. **Workflows --recursive**: `conductor list workflows --recursive` walks subdirectories.
8. **Checkpoints**: `conductor list checkpoints` table and JSON with mocked `CheckpointManager.list_checkpoints`.
9. **Deprecation**: `conductor checkpoints` prints deprecation notice to stderr.
10. **Templates**: `conductor list templates` table and JSON.
11. **Empty states**: Every subcommand handled gracefully when no data exists.
12. **JSON schema stability**: Assert consistent JSON keys across calls.

Run: `uv run pytest tests/test_cli/test_list.py -v` — tests should fail (the file doesn't exist yet or the implementation is incomplete). This confirms you're testing the right surface area.

### Step 3: Implement Tests (if test-worker is pure-test, skip implementation)
This worker writes **tests only**. The implementation (`src/conductor/cli/list_cmd.py`) and `app.py` registration are owned by cli-worker. Your job is to:

- Write thorough, isolated tests that mock all filesystem and external dependencies.
- Use `CliRunner` for end-to-end CLI integration.
- Mock at the correct boundary — see "Mocking Strategy" below.

**Mocking Strategy:**

| Dependency | How to Mock | Why |
|---|---|---|
| `read_pid_files()` | `monkeypatch.setattr("conductor.cli.list_cmd.read_pid_files", lambda: mock_entries)` | Returns running workflow entries; no real PID files needed |
| `CheckpointManager.list_checkpoints()` | `monkeypatch.setattr("conductor.cli.list_cmd.CheckpointManager.list_checkpoints", mock_fn)` | Returns checkpoint data; no real checkpoints needed |
| `_conductor_run_dir()` | `monkeypatch.setattr("conductor.cli.list_cmd._conductor_run_dir", lambda: tmp_path)` | Points event log discovery at temp dir |
| `_list_all_registries()` | `monkeypatch.setattr("conductor.cli.list_cmd._list_all_registries", mock_fn)` | Returns registry data |
| `_list_registry_workflows()` | `monkeypatch.setattr("conductor.cli.list_cmd._list_registry_workflows", mock_fn)` | Returns registry workflow list |
| Event log files (JSONL) | Write real `*.events.jsonl` files into `tmp_path` | Tests defensive parsing (truncated lines, invalid JSON) with real file I/O |
| Workflow YAML files | Write real `*.yaml` / `*.yml` files into `tmp_path` subdirectories | Tests heuristic filtering against real YAML content |
| Template directories | `monkeypatch.setattr("conductor.cli.list_cmd._TEMPLATE_DIRS", [tmp_path / "templates"])` | Points template discovery at temp dir with test template files |
| `load_config()` | `monkeypatch.setattr` or `unittest.mock.patch` | Controls Pydantic parsing in heuristic filter |

**Mapping the mocking surface — read `list_cmd.py` to confirm these paths before writing:**

Run `grep "^from conductor" src/conductor/cli/list_cmd.py` to see the exact import paths. Your monkeypatch targets must match the module where the symbol is *used* (the `list_cmd` module), not where it is *defined*. Example: if `list_cmd.py` does `from conductor.cli.pid import read_pid_files`, then monkeypatch `"conductor.cli.list_cmd.read_pid_files"`, not `"conductor.cli.pid.read_pid_files"`.

**Test file structure:**

```python
"""Tests for conductor list CLI commands."""

import json
import pytest
from pathlib import Path
from typer.testing import CliRunner
from conductor.cli.app import app

runner = CliRunner()


class TestListSummary:
    """conductor list (no subcommand) — summary dashboard."""

    def test_summary_all_empty(self, monkeypatch, tmp_path):
        """When nothing is running, no workflows, no checkpoints — show zero counts."""
        ...

    def test_summary_with_running(self, monkeypatch):
        """With one running workflow, the running count is 1."""
        ...


class TestListRuns:
    """conductor list runs — running workflows table."""

    def test_runs_empty(self, monkeypatch):
        """No PID files → dim empty message, exit 0."""
        ...

    def test_runs_single(self, monkeypatch):
        """One PID file → table with one row."""
        ...

    def test_runs_table_columns(self, monkeypatch):
        """Assert columns: Port, PID, Workflow, Dashboard URL, Started."""
        ...

    def test_runs_json(self, monkeypatch):
        """--json flag emits valid JSON array."""
        ...

    def test_runs_json_keys(self, monkeypatch):
        """JSON output has stable keys: pid, port, workflow, dashboard_url, started_at, run_id, log_file."""
        ...


class TestListRunsRecent:
    """conductor list runs --recent N — event log scanning."""

    def test_recent_empty(self, monkeypatch, tmp_path):
        """No event log files → dim empty message."""
        ...

    def test_recent_single_completed(self, monkeypatch, tmp_path):
        """One event log with workflow_started + workflow_completed."""
        ...

    def test_recent_single_failed(self, monkeypatch, tmp_path):
        """One event log with workflow_started + workflow_failed."""
        ...

    def test_recent_running_matched_by_pid(self, monkeypatch, tmp_path):
        """Event log without terminal event + active PID → status "running"."""
        ...

    def test_recent_truncation(self, monkeypatch, tmp_path):
        """--recent 2 with 5 log files → only 2 rows."""
        ...

    def test_recent_invalid_json_line_skipped(self, monkeypatch, tmp_path):
        """Corrupted last line → skipped, event log still parsed."""
        ...

    def test_recent_empty_file_skipped(self, monkeypatch, tmp_path):
        """Zero valid JSON lines → file skipped with debug log, no crash."""
        ...

    def test_recent_json_keys(self, monkeypatch, tmp_path):
        """JSON output has stable keys: workflow, run_id, started_at, ended_at, status, duration_seconds, log_file."""
        ...


class TestListWorkflows:
    """conductor list workflows — local YAML discovery."""

    def test_workflows_empty(self, monkeypatch, tmp_path):
        """No YAML files → dim empty message."""
        ...

    def test_workflows_single_valid(self, monkeypatch, tmp_path):
        """One YAML with agents: key → shows in table."""
        ...

    def test_workflows_heuristic_filters_non_workflow(self, monkeypatch, tmp_path):
        """YAML without agents:/type:/runtime: → excluded by default."""
        ...

    def test_workflows_all_flag_includes_non_workflow(self, monkeypatch, tmp_path):
        """--all flag includes files that fail the heuristic."""
        ...

    def test_workflows_strips_workflow_config(self, monkeypatch, tmp_path):
        """YAML with type: workflow key passes heuristic."""
        ...

    def test_workflows_recursive(self, monkeypatch, tmp_path):
        """--recursive discovers YAML in subdirectories."""
        ...

    def test_workflows_max_depth(self, monkeypatch, tmp_path):
        """--max-depth 1 stops at one level."""
        ...

    def test_workflows_path_flag(self, monkeypatch, tmp_path):
        """--path <dir> starts search from specified directory."""
        ...

    def test_workflows_table_columns(self, monkeypatch, tmp_path):
        """Assert columns: Name, Path, Agents, Topology."""
        ...

    def test_workflows_json_keys(self, monkeypatch, tmp_path):
        """JSON output has stable keys: name, path, agent_count, has_parallel, has_for_each, has_pipeline, description."""
        ...


class TestListCheckpoints:
    """conductor list checkpoints — checkpoint listing."""

    def test_checkpoints_empty(self, monkeypatch):
        """No checkpoints → dim empty message."""
        ...

    def test_checkpoints_table(self, monkeypatch):
        """Multiple checkpoints → Rich table."""
        ...

    def test_checkpoints_json(self, monkeypatch):
        """--json flag emits valid JSON array."""
        ...

    def test_checkpoints_json_keys(self, monkeypatch):
        """JSON output has stable keys matching CheckpointData fields."""
        ...

    def test_checkpoints_filter_by_workflow(self, monkeypatch):
        """[WORKFLOW] argument filters checkpoints."""
        ...


class TestDeprecation:
    """conductor checkpoints — deprecated alias."""

    def test_deprecation_notice_on_stderr(self, monkeypatch):
        """'conductor checkpoints' prints deprecation notice to stderr."""
        ...

    def test_deprecation_output_matches_list_checkpoints(self, monkeypatch):
        """'conductor checkpoints' produces same stdout as 'conductor list checkpoints'."""
        ...

    def test_deprecation_stderr_not_in_json_mode(self, monkeypatch):
        """--json mode: deprecation on stderr, JSON on stdout — pipe-safe."""
        ...


class TestListTemplates:
    """conductor list templates — template discovery."""

    def test_templates_empty(self, monkeypatch, tmp_path):
        """No template directories with YAML files → dim empty message."""
        ...

    def test_templates_table(self, monkeypatch, tmp_path):
        """Template files found → Rich table with Name, Description, Path."""
        ...

    def test_templates_json(self, monkeypatch, tmp_path):
        """--json flag emits valid JSON array."""
        ...

    def test_templates_json_keys(self, monkeypatch, tmp_path):
        """JSON output has stable keys: name, description, path."""
        ...


class TestListRegistries:
    """conductor list registries — delegates to registry module."""

    def test_registries_empty(self, monkeypatch):
        """No registries → dim empty message."""
        ...

    def test_registries_table(self, monkeypatch):
        """Registries found → Rich table."""
        ...

    def test_registries_json(self, monkeypatch):
        """--json flag emits valid JSON array."""
        ...

    def test_registries_filter_by_name(self, monkeypatch):
        """<name> argument lists workflows in specific registry."""
        ...


class TestJsonSchemaStability:
    """Cross-cutting: ensure JSON output keys are stable across all subcommands."""

    def test_all_subcommand_json_is_valid(self, monkeypatch, tmp_path):
        """Every list subcommand with --json produces parseable JSON array."""
        ...

    def test_keys_match_across_empty_and_populated(self, monkeypatch, tmp_path):
        """Empty JSON output has same keys as populated output (not [] vs [{...}])."""
        ...
```

**Mock entry factory helpers** — write these at module level to keep tests DRY:

```python
def _make_pid_entry(pid=12345, port=8080, workflow="qa.yaml", started_at="2026-01-01T00:00:00", run_id="abc12345"):
    """Build a mock PID entry dict matching read_pid_files() output."""
    return {
        "pid": pid,
        "port": port,
        "workflow": workflow,
        "started_at": started_at,
        "run_id": run_id,
        "log_file": f"/tmp/conductor/conductor-qa-{started_at[:10]}-{run_id}.events.jsonl",
        "file": f"/home/user/.conductor/runs/{pid}.pid",
    }


def _make_checkpoint(workflow_path="qa.yaml", created_at="2026-01-01T00:00:00", ...):
    """Build a mock CheckpointData instance."""
    ...


def _write_event_log(path, events):
    """Write a list of event dicts as JSONL to path."""
    with open(path, "w") as f:
        for evt in events:
            f.write(json.dumps(evt) + "\n")


def _write_yaml(path, content_dict):
    """Write a dict as YAML to path."""
    import yaml
    with open(path, "w") as f:
        yaml.dump(content_dict, f)
```

**Key testing patterns:**

1. **CLI invocation**: `result = runner.invoke(app, ["list", "runs"])` — always use `app` (the full Typer app from `conductor.cli.app`) to test through the real CLI registration.

2. **Asserting Rich output**: Rich tables render ANSI-escaped text. Use substring assertions: `assert "8080" in result.stdout`, `assert "qa.yaml" in result.stdout`. For structured assertions, use `--json` mode and `json.loads(result.stdout)`.

3. **Asserting exit codes**: `assert result.exit_code == 0` for success, `assert result.exit_code == 1` for errors.

4. **Asserting stderr**: Deprecation notices go to stderr: `assert "Deprecated" in result.stderr`. Check that `result.stdout` is clean (no deprecation text in stdout).

5. **Temp directory isolation**: Use `tmp_path` fixture — never write to real `$TMPDIR` or `~/.conductor/`. Point all discovery functions at `tmp_path` via monkeypatch.

6. **JSON schema assertion**: After loading JSON output, assert the expected keys are present (not just that it parses). Example:
   ```python
   data = json.loads(result.stdout)
   for entry in data:
       assert set(entry.keys()) == {"pid", "port", "workflow", "dashboard_url", "started_at", "run_id", "log_file"}
   ```

### Step 4: Verify
Run the test suite scoped to your file:

```bash
uv run pytest tests/test_cli/test_list.py -v
```

Fix all failures. Common pitfalls:

- **Wrong monkeypatch path**: The import in `list_cmd.py` determines the path. If `list_cmd.py` does `from conductor.cli.pid import read_pid_files`, patch `"conductor.cli.list_cmd.read_pid_files"`.
- **Missing mock**: If a test fails with `FileNotFoundError`, you're missing a monkeypatch for a filesystem dependency.
- **`runner.invoke` returns before Typer output**: `CliRunner` is synchronous — output is available immediately in `result.stdout` / `result.stderr`.
- **Rich markup in output**: Rich tables contain ANSI codes. Use `result.stdout` (raw string) for substring checks, not `result.output` (which may strip styles).

If tests pass, run lint and typecheck:

```bash
make lint
make typecheck
```

Fix any lint/type issues in the test file before proceeding. Note: test files have slightly relaxed lint rules (e.g., longer functions are acceptable), but they must still pass `ruff` with the project config.

### Step 5: Manual Verification
Run the actual CLI command to verify the test assumptions match reality:

```bash
# Summary (may show zeros if nothing is running — that's fine)
uv run conductor list

# Runs (should show running workflows if any exist, or empty message)
uv run conductor list runs

# Workflows (should discover example workflows in examples/)
uv run conductor list workflows --path examples/

# Workflows recursive
uv run conductor list workflows --recursive --path examples/

# Checkpoints
uv run conductor list checkpoints

# Deprecation notice
uv run conductor checkpoints 2>&1 | head -5

# Templates
uv run conductor list templates

# JSON output
uv run conductor list runs --json
uv run conductor list workflows --json --path examples/
uv run conductor list checkpoints --json
```

Confirm:
- All commands exit 0.
- Rich tables render with visible columns.
- `--json` output is valid, parseable JSON arrays.
- The deprecation notice for `conductor checkpoints` only appears on stderr.
- Empty states show a dim message (not a crash or traceback).

## Example Handoff

CRITICAL: The Example Handoff section sets the upper bound of expected worker effort.
Make it realistic, specific, and thorough. Workers pattern-match against it —
the effort level shown here is the effort level you will receive.
A thin example produces thin implementations; a thorough example produces thorough ones.

```yaml
salient_summary: "Wrote 42 pytest tests covering all list subcommands, both output modes, empty states, deprecation notice, and JSON schema stability"
what_was_implemented: >
  Created tests/test_cli/test_list.py with 42 test methods across 8 test classes:
  TestListSummary (2 tests) — summary dashboard with running count.
  TestListRuns (4 tests) — running workflow table and JSON output with stable keys.
  TestListRunsRecent (8 tests) — event log scanning, completed/failed/running status derivation,
  --recent truncation, invalid JSON line tolerance, empty file skipping, stable JSON keys.
  TestListWorkflows (10 tests) — YAML discovery with heuristic filtering, --all flag,
  --recursive, --max-depth, --path, topology tags parsing, stable JSON keys.
  TestListCheckpoints (5 tests) — table and JSON output, workflow filtering, stable keys.
  TestDeprecation (3 tests) — stderr deprecation notice, output parity with list checkpoints,
  pipe-safety in JSON mode.
  TestListTemplates (4 tests) — template table and JSON, empty state, stable keys.
  TestListRegistries (4 tests) — delegation to registry module, table and JSON, name filtering.
  TestJsonSchemaStability (2 tests) — all subcommands produce valid JSON, consistent keys
  across empty and populated states.
  Each test class uses monkeypatch to mock filesystem dependencies (read_pid_files,
  CheckpointManager.list_checkpoints, _conductor_run_dir, _list_all_registries,
  _list_registry_workflows) at the list_cmd module boundary. Event log and YAML file
  tests use tmp_path for real file I/O with hand-crafted JSONL and YAML fixtures.
what_was_left_undone: >
  No integration tests with real running workflows (requires a live conductor instance
  with a real provider — out of scope for unit tests). No performance benchmarks.
verification:
  commands_run:
    - command: "uv run pytest tests/test_cli/test_list.py -v"
      exit_code: 0
      observation: "42 tests passed in 1.23s"
    - command: "make lint"
      exit_code: 0
      observation: "All checks passed — no new lint violations"
    - command: "make typecheck"
      exit_code: 0
      observation: "No type errors in test file or list_cmd.py"
  interactive_checks:
    - action: "uv run conductor list"
      observed: "Rich panel with counts: Running 0, Recent 0, Workflows 0, Templates 0"
    - action: "uv run conductor list runs --json"
      observed: "Valid JSON array '[]' printed to stdout, exit 0"
    - action: "uv run conductor list workflows --path examples/"
      observed: "Rich table listing example YAML files with Name, Path, Agents, Topology columns"
    - action: "uv run conductor checkpoints 2>&1"
      observed: "Stderr: [dim]Deprecated: use 'conductor list checkpoints' instead[/dim]; stdout: checkpoint table (or empty message)"
    - action: "uv run conductor list templates --json | python -m json.tool"
      observed: "Valid JSON array of template objects with name, description, path keys"
tests_added:
  - file: "tests/test_cli/test_list.py"
    cases:
      - name: "test_summary_all_empty"
        description: "When nothing is running — show zero counts panel"
      - name: "test_runs_empty"
        description: "No PID files → dim empty message, exit 0"
      - name: "test_runs_single"
        description: "One PID file → table with one row, correct columns"
      - name: "test_runs_json"
        description: "--json emits valid JSON array"
      - name: "test_runs_json_keys"
        description: "JSON output has stable schema keys"
      - name: "test_recent_empty"
        description: "No event log files → dim empty message"
      - name: "test_recent_single_completed"
        description: "Event log with started+completed → status completed"
      - name: "test_recent_single_failed"
        description: "Event log with started+failed → status failed"
      - name: "test_recent_running_matched_by_pid"
        description: "No terminal event + active PID → status running"
      - name: "test_recent_truncation"
        description: "--recent 2 with 5 logs → only 2 rows"
      - name: "test_recent_invalid_json_line_skipped"
        description: "Corrupted last line → skipped, file still parsed"
      - name: "test_recent_empty_file_skipped"
        description: "Zero valid lines → file skipped, no crash"
      - name: "test_recent_json_keys"
        description: "JSON output has stable keys for run history"
      - name: "test_workflows_empty"
        description: "No YAML files → dim empty message"
      - name: "test_workflows_single_valid"
        description: "YAML with agents: key → shown in table"
      - name: "test_workflows_heuristic_filters_non_workflow"
        description: "Non-workflow YAML excluded by default"
      - name: "test_workflows_all_flag_includes_non_workflow"
        description: "--all includes all YAML files"
      - name: "test_workflows_strips_workflow_config"
        description: "type: workflow key passes heuristic"
      - name: "test_workflows_recursive"
        description: "--recursive discovers YAML in subdirectories"
      - name: "test_workflows_max_depth"
        description: "--max-depth 1 stops at one level"
      - name: "test_workflows_path_flag"
        description: "--path starts search from specified directory"
      - name: "test_workflows_table_columns"
        description: "Table has correct column headers"
      - name: "test_workflows_json_keys"
        description: "JSON output has stable schema keys"
      - name: "test_checkpoints_empty"
        description: "No checkpoints → dim empty message"
      - name: "test_checkpoints_table"
        description: "Checkpoints render as Rich table"
      - name: "test_checkpoints_json"
        description: "--json emits valid JSON array"
      - name: "test_checkpoints_json_keys"
        description: "JSON output has stable CheckpointData keys"
      - name: "test_checkpoints_filter_by_workflow"
        description: "[WORKFLOW] argument filters results"
      - name: "test_deprecation_notice_on_stderr"
        description: "Deprecation notice printed to stderr"
      - name: "test_deprecation_output_matches_list_checkpoints"
        description: "Same stdout as conductor list checkpoints"
      - name: "test_deprecation_stderr_not_in_json_mode"
        description: "JSON mode: deprecation on stderr only"
      - name: "test_templates_empty"
        description: "No templates → dim empty message"
      - name: "test_templates_table"
        description: "Templates render as Rich table"
      - name: "test_templates_json"
        description: "--json emits valid JSON array"
      - name: "test_templates_json_keys"
        description: "JSON output has stable template keys"
      - name: "test_registries_empty"
        description: "No registries → dim empty message"
      - name: "test_registries_table"
        description: "Registries render as Rich table"
      - name: "test_registries_json"
        description: "--json emits valid JSON array"
      - name: "test_registries_filter_by_name"
        description: "<name> argument filters to specific registry"
      - name: "test_all_subcommand_json_is_valid"
        description: "Every list subcommand --json produces parseable JSON"
      - name: "test_keys_match_across_empty_and_populated"
        description: "Empty and populated JSON have same key sets"
return_to_orchestrator: false
discovered_issues: []
skill_name: "test-worker"
skill_feedback: []
```
