---
name: cli-worker
description: Implements Typer CLI subcommands in the Conductor CLI, including command registration, Rich table/JSON output, and integration with existing Conductor primitives.
---

# Cli-Worker

NOTE: Startup and cleanup are handled by worker-base. This skill defines the WORK PROCEDURE.

## Required Skills and Tools

- **Filesystem tools:** `view`, `edit`, `create`, `glob`, `grep` — for reading existing code, creating new files, and modifying `app.py` registration.
- **Bash:** `uv run pytest`, `uv run ty`, `uv run ruff` — for running tests, typecheck, and lint.
- **Python 3.12+** with `typer`, `rich`, `pyyaml`, `pathlib`, `json` — all already in `pyproject.toml`; no new dependencies.
- **Conductor internals:** Import from `conductor.cli.pid` (`read_pid_files`), `conductor.engine.checkpoint` (`CheckpointManager.list_checkpoints`, `_conductor_run_dir`), `conductor.cli.registry` (`_list_all_registries`, `_list_registry_workflows`), `conductor.config.loader` (`load_config`).

## Work Procedure

### Step 1: Understand Your Feature
Read your feature description and fulfills assertions carefully.
Read relevant sections of architecture.md to understand where your code goes.

Key architecture decisions for cli-worker:
- **All new logic lives in a single new file:** `src/conductor/cli/list_cmd.py`
- **The only existing-file modification** is registering the new Typer group in `src/conductor/cli/app.py` and wrapping the deprecated `checkpoints` command with a stderr notice.
- **No new dependencies** — use `typer`, `rich`, `pyyaml`, `pathlib`, `json`.
- **Rich tables go to stdout** (`output_console`), not stderr — list output IS the primary result.
- **Every subcommand supports `--json`** for machine-readable output.
- **Defensive I/O:** event log parsing is line-by-line, tolerates truncated last lines; YAML heuristic reads at most 2 KB per file; missing directories/files produce empty results, not crashes.

Before writing any code, read these files to understand the integration surface:
- `src/conductor/cli/app.py` — see how `registry_app` is registered, how the existing `checkpoints` command is structured, and where to add `list_app`.
- `src/conductor/cli/pid.py` — understand the return shape of `read_pid_files()`.
- `src/conductor/engine/checkpoint.py` — find `CheckpointManager.list_checkpoints()` and `_conductor_run_dir()`.
- `src/conductor/cli/registry.py` — find `_list_all_registries()` and `_list_registry_workflows()`.

### Step 2: Test First (TDD)
Write failing tests before writing implementation code.

Create `tests/test_cli/test_list.py`. The test file must cover:

**`list runs` tests:**
- Mock `read_pid_files()` returning 0, 1, and 3 entries; assert Rich table row count and JSON array length.
- Mock event log directory with `*.events.jsonl` files; assert `--recent N` truncation, status derivation (running/completed/failed), and sorting by start time descending.
- Test empty state: no PID files → dim "No running workflows" message.
- Test `--json` flag: valid JSON array output to stdout.
- Test truncated event log lines: invalid JSON lines are silently skipped, not crashed.

**`list workflows` tests:**
- Create temp directory with `.yaml` files: some with `agents:` key (valid), some without (config files). Assert heuristic filter includes only valid ones.
- Test `--all` flag: all `.yaml` files included regardless of content.
- Test `--recursive` with subdirectories; assert `--max-depth` enforcement.
- Test `--path` flag: search from a different root directory.
- Test `--json` flag: valid JSON array with full metadata (name, path, agent_count, topology tags).

**`list checkpoints` tests:**
- Mock `CheckpointManager.list_checkpoints()` returning 0, 1, and multiple entries; assert table rows and JSON output.
- Test deprecation wrapper: `conductor checkpoints` still works but emits `[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]` to stderr.

**`list registries` tests:**
- Verify delegation to existing `_list_all_registries()` produces correct output.
- Test `conductor list registries <name>` delegates to `_list_registry_workflows()`.

**`list templates` tests:**
- Mock template directory with YAML files containing comment headers; assert name/description extraction.
- Test `--json` flag.

**Summary (`conductor list` no subcommand) tests:**
- Mock all data sources; assert summary panel shows correct counts and hints for each subcommand.

Run: `uv run pytest tests/test_cli/test_list.py -v` — confirm tests fail (no implementation yet).

### Step 3: Implement

**Create `src/conductor/cli/list_cmd.py`** with the following structure:

```python
"""`conductor list` — Unified discovery of workflows, runs, checkpoints, and more."""

import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

# ... imports from conductor internals

output_console = Console()  # stdout for primary output
console = Console(stderr=True)  # stderr for errors/deprecation

list_app = typer.Typer(
    name="list",
    help="Discover workflows, runs, checkpoints, and more.",
    no_args_is_help=False,
)

@list_app.callback(invoke_without_command=True)
def list_summary() -> None:
    """Show summary dashboard with counts and hints."""
    # Gather counts: running workflows, recent runs, local workflows, registries, templates
    # Print a Rich panel with each count and a dim hint for the full subcommand
    ...

@list_app.command("runs")
def list_runs(
    recent: int = typer.Option(0, "--recent", help="Show last N completed/failed runs"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON array"),
) -> None:
    """List running background workflows and recent run history."""
    ...

@list_app.command("workflows")
def list_workflows(
    path: Path = typer.Option(Path.cwd(), "--path", help="Search root directory"),
    recursive: bool = typer.Option(False, "--recursive", help="Walk subdirectories"),
    max_depth: int = typer.Option(3, "--max-depth", help="Recursion depth limit"),
    show_all: bool = typer.Option(False, "--all", help="Show all YAML files (skip heuristic)"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON array"),
) -> None:
    """Discover local workflow YAML files with heuristic filtering."""
    ...

@list_app.command("checkpoints")
def list_checkpoints(
    workflow: Path | None = typer.Argument(None, help="Filter by workflow YAML path"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON array"),
) -> None:
    """List saved checkpoints for resumable workflows."""
    ...

@list_app.command("registries")
def list_registries(
    name: str | None = typer.Argument(None, help="Registry name to list workflows from"),
) -> None:
    """List configured registries or workflows in a specific registry."""
    ...

@list_app.command("templates")
def list_templates(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON array"),
) -> None:
    """List built-in and plugin-provided workflow templates."""
    ...
```

**Implementation order and guidance:**

1. **Shared helpers first:**
   - `_scan_event_logs(recent: int) -> list[dict]`: glob `$TMPDIR/conductor/conductor-*.events.jsonl`, parse first and last valid JSON lines per file, derive status. Cross-reference with PID files to mark running workflows correctly. Sort by started_at descending, truncate to `recent`.
   - `_discover_workflows(root, recursive, max_depth) -> list[Path]`: walk for `*.yaml`/`*.yml`. If recursive, use `Path.rglob` with depth check.
   - `_heuristic_filter(paths, show_all) -> list[dict]`: read first 2 KB of each file, string-search for `agents:`, `type: workflow`, or `runtime:`. If matched, parse with `yaml.safe_load` and extract metadata. Return all if `show_all`.
   - `_list_templates_from_dirs() -> list[dict]`: discover `plugins/conductor-workflow-creator/assets/templates/`, parse YAML frontmatter comments.
   - `_list_checkpoints_impl(workflow: Path | None) -> list[dict]`: shared between `list checkpoints` command and deprecated `checkpoints` alias.

2. **Rich table renderers:** `_build_running_table`, `_build_recent_table`, `_build_workflow_table`, `_build_checkpoint_table`, `_build_template_table`. Each accepts a list of dicts and prints a `rich.table.Table` to `output_console`.

3. **JSON renderers:** `_build_runs_json`, `_build_workflows_json`, `_build_checkpoints_json`, `_build_templates_json`. Each accepts a list of dicts and prints `json.dumps(array, default=str)` via `output_console.print_json()`.

4. **Subcommand wiring:** Each `@list_app.command` function calls the appropriate helper and renderer, branching on `json_output` flag.

**Modify `src/conductor/cli/app.py`:**

1. **Register the new group** near the existing `app.add_typer(registry_app)` line:
   ```python
   from conductor.cli.list_cmd import list_app
   app.add_typer(list_app)
   ```

2. **Wrap the deprecated `checkpoints` command:**
   - Add `hidden=True` to its `@app.command()` decorator.
   - At the top of the function body, add:
     ```python
     console.print("[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]")
     ```
   - Replace the body with a delegation to `_list_checkpoints_impl(workflow)` from `list_cmd.py`.

**Key patterns to follow:**
- Use `output_console` (stdout) for table/JSON output; `console` (stderr) for errors and deprecation notices.
- All filesystem I/O is defensive: `try/except` around file reads, skip malformed files with a debug log, never crash.
- Heuristic YAML scan: string-check before `yaml.safe_load` — avoid full Pydantic validation until the cheap check passes.
- `--recent` cross-references PID files: a JSONL file matching an active PID's `run_id` shows as "running" even without a terminal event.
- Empty states print a dim message (e.g., `[dim]No running workflows found.[/dim]`) — never an error.

### Step 4: Verify

Run the scoped commands in this order, fixing all failures before proceeding:

```bash
# Tests (scoped to the new file)
uv run pytest tests/test_cli/test_list.py -v

# Type check (scoped to the cli directory)
uv run ty src/conductor/cli/

# Lint AND format. The milestone review gate runs `ruff check src tests &&
# ruff format --check src tests` across the WHOLE tree — broader than the
# files you changed. `ruff check` passing is NOT enough: unformatted code
# fails `ruff format --check` and resets the entire milestone to pending.
# Always auto-format before handing off:
uv run ruff format src tests
uv run ruff check --fix src tests

# Confirm against the EXACT command the milestone validator runs — this must
# exit 0 or your milestone review will fail:
uv run ruff check src tests && uv run ruff format --check src tests
```

If any existing tests break due to the `app.py` deprecation wrapper change, fix them — the wrapper must preserve backward compatibility for scripts parsing checkpoint stdout.

### Step 5: Manual Verification

Run these commands manually and verify the output:

1. **Summary dashboard:**
   ```bash
   uv run conductor list
   ```
   Verify: Rich panel with counts for running workflows, recent runs, local workflows, registries, templates. Each count has a dim hint like `[dim]Use 'conductor list runs' for details[/dim]`.

2. **Running workflows (table):**
   ```bash
   uv run conductor list runs
   ```
   Verify: Rich table with columns Port, PID, Workflow, Dashboard URL, Started. If nothing is running, a dim "No running workflows found." message.

3. **Running workflows (JSON):**
   ```bash
   uv run conductor list runs --json
   ```
   Verify: Valid JSON array (pipe through `python -m json.tool`). Each object has `pid`, `port`, `workflow`, `started_at`, `run_id`, `dashboard_url`.

4. **Recent runs:**
   ```bash
   uv run conductor list runs --recent 5
   uv run conductor list runs --recent 5 --json
   ```
   Verify: Table shows last 5 completed/failed runs sorted by start time. JSON array has at most 5 entries with `workflow`, `run_id`, `started_at`, `ended_at`, `status`, `duration_seconds`.

5. **Local workflow discovery:**
   ```bash
   uv run conductor list workflows
   uv run conductor list workflows --recursive
   uv run conductor list workflows --path examples/
   uv run conductor list workflows --all
   uv run conductor list workflows --json
   ```
   Verify: Table shows workflow YAML files with Name, Path, Agent count, Topology. `--all` includes config files. `--recursive` descends into subdirectories.

6. **Checkpoints (with deprecation):**
   ```bash
   uv run conductor list checkpoints
   uv run conductor checkpoints 2>/tmp/deprecation.txt && cat /tmp/deprecation.txt
   ```
   Verify: Both produce identical output. The old command prints deprecation notice to stderr.

7. **Registries and templates:**
   ```bash
   uv run conductor list registries
   uv run conductor list templates
   uv run conductor list templates --json
   ```
   Verify: Registry output matches `conductor registry list`. Templates show name, description, path.

8. **Help output:**
   ```bash
   uv run conductor list --help
   uv run conductor --help
   ```
   Verify: `list` group appears in `conductor --help`. `conductor list --help` shows all subcommands with their options.

## Example Handoff

CRITICAL: The Example Handoff section sets the upper bound of expected worker effort.
Make it realistic, specific, and thorough. Workers pattern-match against it —
the effort level shown here is the effort level you will receive.
A thin example produces thin implementations; a thorough example produces thorough ones.

```yaml
salient_summary: "Implemented `conductor list runs` subcommand with Rich table and JSON output"
what_was_implemented: >
  Created `src/conductor/cli/list_cmd.py` with `list_app` Typer group, `list_runs` command,
  shared `_scan_event_logs()` helper, and Rich table / JSON renderers. Registered `list_app`
  in `app.py` via `app.add_typer(list_app)`. The `list runs` command displays running background
  workflows from PID files (Port, PID, Workflow, Dashboard URL, Started columns) and recent run
  history from JSONL event logs when `--recent N` is passed. The `--json` flag emits a JSON
  array for scripting. Event log parsing is defensive: line-by-line, skipping invalid JSON,
  cross-referencing PID files to correctly mark active runs as "running". Empty states print
  dim informational messages to stdout, not errors to stderr. The deprecated `conductor
  checkpoints` command in `app.py` now prints a dim deprecation notice to stderr and delegates
  to `_list_checkpoints_impl()` in `list_cmd.py`.
what_was_left_undone: >
  `list workflows`, `list registries`, `list templates`, and the `list` summary callback
  are stubbed out but not yet implemented. The `list checkpoints` command shell exists in
  `list_cmd.py` but delegates to the existing `CheckpointManager.list_checkpoints()` —
  the shared `_list_checkpoints_impl()` helper is implemented and used by both the new
  command and the deprecated alias.
verification:
  commands_run:
    - command: "uv run pytest tests/test_cli/test_list.py -v"
      exit_code: 0
      observation: "23 tests passed — covers running table, JSON output, empty state, recent filtering, event log parsing edge cases, deprecation notice, and cross-reference with PID files"
    - command: "uv run ty src/conductor/cli/"
      exit_code: 0
      observation: "No type errors in cli/ directory"
    - command: "uv run ruff check src/conductor/cli/list_cmd.py src/conductor/cli/app.py tests/test_cli/test_list.py"
      exit_code: 0
      observation: "No lint violations"
  interactive_checks:
    - action: "uv run conductor list runs"
      observed: "Rich table with Port, PID, Workflow, Dashboard URL, Started columns. Dim 'No running workflows found.' when no PID files exist."
    - action: "uv run conductor list runs --json | python -m json.tool"
      observed: "Valid JSON array. Each object has pid, port, workflow, started_at, run_id, dashboard_url keys."
    - action: "uv run conductor list runs --recent 5"
      observed: "Table of last 5 completed/failed runs from event logs, sorted by start time descending. Correct status column (completed/failed/running)."
    - action: "uv run conductor checkpoints 2>/tmp/dep.txt && cat /tmp/dep.txt"
      observed: "Deprecation notice printed to stderr. Output identical to 'conductor list checkpoints'."
    - action: "uv run conductor list --help"
      observed: "Shows runs, workflows, checkpoints, registries, templates subcommands with their options."
tests_added:
  - file: "tests/test_cli/test_list.py"
    cases:
      - name: "test_list_runs_empty"
        description: "No PID files → dim message, empty JSON array"
      - name: "test_list_runs_single"
        description: "One PID file → table with 1 row, correct column values"
      - name: "test_list_runs_multiple"
        description: "Three PID files → table with 3 rows sorted by port"
      - name: "test_list_runs_json"
        description: "--json flag → valid JSON array with correct keys"
      - name: "test_list_runs_recent"
        description: "--recent 5 truncates to 5 entries from event logs"
      - name: "test_list_runs_recent_no_logs"
        description: "No event logs → empty JSON array, dim message"
      - name: "test_list_runs_recent_truncated_jsonl"
        description: "Truncated last JSON line → skipped silently, other lines parsed"
      - name: "test_list_runs_recent_crossref_pid"
        description: "JSONL with no terminal event but matching PID → status=running"
      - name: "test_list_runs_recent_status_completed"
        description: "JSONL ending with workflow_completed → status=completed"
      - name: "test_list_runs_recent_status_failed"
        description: "JSONL ending with workflow_failed → status=failed"
      - name: "test_list_runs_recent_sort_order"
        description: "Multiple event logs sorted by started_at descending"
      - name: "test_deprecation_notice"
        description: "conductor checkpoints emits deprecation to stderr, delegates correctly"
      - name: "test_deprecation_stdout_unchanged"
        description: "conductor checkpoints stdout matches list checkpoints stdout"
      - name: "test_list_checkpoints_empty"
        description: "No checkpoints → dim message, empty JSON array"
      - name: "test_list_checkpoints_with_workflow_filter"
        description: "Workflow path argument filters checkpoint results"
      - name: "test_list_checkpoints_json"
        description: "--json flag → valid JSON array of checkpoint objects"
      - name: "test_list_help_shows_subcommands"
        description: "conductor list --help lists all subcommands"
      - name: "test_conductor_help_shows_list_group"
        description: "conductor --help includes 'list' in command listing"
      - name: "test_event_log_scan_empty_dir"
        description: "Empty TMPDIR → empty results, no crash"
      - name: "test_event_log_scan_missing_dir"
        description: "Missing TMPDIR → empty results, no crash"
      - name: "test_scan_event_logs_invalid_json_skipped"
        description: "Line with invalid JSON → skipped, valid lines parsed"
      - name: "test_scan_event_logs_zero_valid_lines"
        description: "File with no valid JSON lines → skipped with debug log"
      - name: "test_read_pid_files_mocked"
        description: "Mock returns 0, 1, 3 entries → correct table rows and JSON count"
return_to_orchestrator: false
discovered_issues: []
skill_name: "cli-worker"
skill_feedback: []
```

## When to Return to Orchestrator

Return immediately (set `return_to_orchestrator: true`) if:
- `uv run pytest` on the existing test suite fails before any changes (pre-existing breakage).
- `read_pid_files()`, `CheckpointManager.list_checkpoints()`, `_conductor_run_dir()`, `_list_all_registries()`, or `_list_registry_workflows()` have a different signature than documented — the architecture assumes these exist with specific return shapes.
- The `app.py` structure has diverged significantly from the architecture document (e.g., `checkpoints` command moved, `registry_app` registration changed).
- A required test scenario cannot be meaningfully tested because the underlying Conductor primitives cannot be mocked (e.g., `yaml.safe_load` behavior changed in a way that breaks heuristic filtering).
- The `--json` output format cannot be made stable across the subcommands due to upstream data model inconsistencies.


## Pre-Implementation Checklist

Before writing any code for a CLI feature, always:
1. Read the relevant existing source file(s) (e.g., `src/conductor/cli/list_cmd.py`)
2. Read the corresponding test file(s) (e.g., `tests/test_cli/test_list.py`)
3. Understand the current implementation state and patterns used
4. Only then proceed to write tests and implementation

This prevents handoffs where "pending: read files" is the only outcome.
