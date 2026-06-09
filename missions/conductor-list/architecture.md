# Architecture: `conductor list`

## System Overview

`conductor list` is a read-only CLI command group that provides unified discovery of running
workflows, recent runs, available workflow YAML files, checkpoints, registry-published
workflows, and built-in templates. It consolidates discovery into a single `list`
subcommand group with:

- **`conductor list` (no subcommand)** — Summary dashboard with counts and hints.
- **`conductor list runs`** — Table/JSON of running background workflows and recent history.
- **`conductor list workflows`** — Local YAML file discovery with heuristic filtering.
- **`conductor list checkpoints`** — Drop-in replacement for `conductor checkpoints` (deprecated alias kept).
- **`conductor list registries`** — Delegates to existing `conductor registry list`.
- **`conductor list templates`** — Lists built-in workflow templates.

Every subcommand supports `--json` for machine-readable output.

---

## Directory Structure

```
src/conductor/
├── cli/
│   ├── app.py              # EXISTING — register `list_app` Typer group here
│   ├── list_cmd.py          # NEW — all `list` CLI commands live here
│   ├── pid.py              # EXISTING — `read_pid_files()` for running workflow discovery
│   ├── registry.py         # EXISTING — `registry_app` group (delegated to by `list registries`)
│   └── run.py              # EXISTING — `_conductor_run_dir` for event log path resolution
├── engine/
│   ├── checkpoint.py       # EXISTING — `CheckpointManager.list_checkpoints()` for checkpoint listing
│   └── event_log.py        # EXISTING — `EventLogSubscriber` writes JSONL event logs
└── config/
    ├── schema.py           # EXISTING — `WorkflowConfig`, `WorkflowDef`, `AgentDef` models
    └── loader.py           # EXISTING — `load_config()` for parsing YAML

plugins/conductor-workflow-creator/
└── assets/
    └── templates/          # EXISTING — built-in template YAML files (pipeline, fan-out, loop)

tests/
└── test_cli/
    └── test_list.py        # NEW — comprehensive CLI tests for all `list` subcommands
```

**Key principle:** All new code lives in a single new file (`src/conductor/cli/list_cmd.py`).
The only modification to existing files is registering the new Typer group in `app.py`.

---

## Data Models

### PID Entry (from `cli/pid.py`, consumed by `list runs`)

```
{
    "pid": int,           # Process ID
    "port": int,          # Web dashboard port
    "workflow": str,      # Path to workflow YAML file
    "started_at": str,    # ISO-8601 timestamp
    "run_id": str,        # 8-char hex run identifier
    "log_file": str,      # Path to JSONL event log file
    "file": str           # Path to the PID file (added by read_pid_files)
}
```

### Event Log Entry (from JSONL files, consumed by `list runs --recent`)

Each line in `*.events.jsonl`:
```json
{"type": "workflow_failed", "timestamp": 1717000000.0, "data": {...}}
{"type": "workflow_completed", "timestamp": 1717000010.0, "data": {...}}
```

Key event types used for derivation:
- `workflow_started` → workflow name, start time
- `workflow_completed` → end time, status="completed"
- `workflow_failed` → end time, status="failed"
- Absence of terminal event → status="running"

### CheckpointData (from `engine/checkpoint.py`, consumed by `list checkpoints`)

```python
@dataclass
class CheckpointData:
    version: int
    workflow_path: str
    workflow_hash: str
    created_at: str         # ISO-8601 timestamp
    failure: dict           # {error_type, message, agent, iteration}
    inputs: dict
    current_agent: str
    context: dict
    limits: dict
    copilot_session_ids: dict
    file_path: Path
    instructions_preamble: str | None
    run_id: str
    event_log_path: str
```

### Workflow File Metadata (heuristic scan, consumed by `list workflows`)

Derived from YAML front-matter (first 2 KB):
```
{
    "name": str,            # workflow.name from YAML, else stem
    "path": str,            # Absolute file path
    "agent_count": int,     # len(agents) from YAML
    "has_parallel": bool,   # parallel list is non-empty
    "has_for_each": bool,   # for_each list is non-empty
    "has_pipeline": bool,   # agents only (no parallel/for_each)
    "description": str | None  # workflow.description from YAML
}
```

### Template Metadata (from YAML frontmatter comments, consumed by `list templates`)

Template YAML files start with a comment block:
```yaml
# Template Name
# Description line
#
# Use when: ...
# Run: conductor run template.yaml ...
```

Extracted fields:
```
{
    "name": str,         # First comment line or filename stem
    "description": str,  # Second comment line
    "path": str          # Absolute file path
}
```

### Run History Entry (derived from event logs, consumed by `list runs --recent`)

```
{
    "workflow": str,       # Workflow name from event log filename
    "run_id": str,         # 8-char hex from event log filename
    "started_at": str,     # ISO-8601 from first event
    "ended_at": str | None, # ISO-8601 from last event, or null if running
    "status": "running" | "completed" | "failed",
    "duration_seconds": float | None,  # ended_at - started_at, or null
    "log_file": str        # Path to the event log file
}
```

---

## API / Interface Layer

### CLI Registration (in `app.py`)

A new Typer group `list_app` is registered on the main app:

```python
# In app.py, near the existing registry_app registration:
from conductor.cli.list_cmd import list_app
app.add_typer(list_app)
```

### Command Structure (in `list_cmd.py`)

```
list_app = typer.Typer(name="list", help="Discover workflows, runs, checkpoints, and more.", no_args_is_help=False)

@list_app.callback()
def list_summary() -> None       # `conductor list` — summary dashboard

@list_app.command("runs")
def list_runs(
    recent: int = 0,             # --recent N: show last N completed/failed runs
    json_output: bool = False,   # --json: emit JSON array
) -> None

@list_app.command("workflows")
def list_workflows(
    path: Path = Path.cwd(),     # --path: search root directory
    recursive: bool = False,     # --recursive: walk subdirectories
    max_depth: int = 3,          # --max-depth: recursion limit
    show_all: bool = False,      # --all: show all YAML files (skip heuristic)
    json_output: bool = False,   # --json: emit JSON array
) -> None

@list_app.command("checkpoints")
def list_checkpoints(
    workflow: Path | None = None, # [WORKFLOW] argument
    json_output: bool = False,    # --json: emit JSON array
) -> None

@list_app.command("registries")
def list_registries(
    name: str | None = None,      # [NAME] argument
) -> None

@list_app.command("templates")
def list_templates(
    json_output: bool = False,    # --json: emit JSON array
) -> None
```

### Output Contract

- **Default mode:** Rich `Table` to `output_console` (stdout). Empty states print a dim message to `output_console`.
- **`--json` mode:** `output_console.print_json(json.dumps(array))` to stdout. JSON array of objects matching the data models above.
- **Errors:** Printed to `console` (stderr) as Rich `[bold red]Error:[/bold red]` messages.
- **Exit codes:** 0 on success, 1 on errors (missing file, unreadable event log).

### Auth Requirements

None. All subcommands are read-only filesystem operations. The `list registries` delegation to `conductor registry list` may trigger HTTP calls to GitHub for tag listing (existing behavior).

---

## Service Layer

### `list_cmd.py` — Module Responsibilities

**`_build_running_table(entries)` / `_build_runs_json(entries)`**
- Format `read_pid_files()` output as Rich table or JSON list.
- Columns: Port, PID, Workflow (stem), Dashboard URL (`http://127.0.0.1:{port}`), Started.

**`_scan_event_logs(recent: int)` → `list[RunHistoryEntry]`**
- Glob `$TMPDIR/conductor/conductor-*.events.jsonl`.
- For each file: parse first line → start time; parse last valid JSON line → end time + status.
- Tolerate truncated last lines (parse line-by-line, skip invalid JSON).
- Sort by started_at descending, limit to `recent`.
- For JSONL files corresponding to currently-running workflows (matched by `run_id` in PID files), mark status as "running" even if no terminal event exists.

**`_discover_workflows(root, recursive, max_depth)` → `list[Path]`**
- Walk `root` for `*.yaml` / `*.yml` files.
- If `recursive`: use `Path.rglob` with `max_depth` enforced by path depth check.
- Return sorted list of matching paths.

**`_heuristic_filter(paths, show_all)` → `list[WorkflowFileMeta]`**
- For each file, read first 2 KB.
- Quick string check for `agents:`, `type: workflow`, or `runtime:`.
- If matched, parse with `yaml.safe_load` and extract metadata.
- Return filtered list (or all if `show_all`).

**`_build_workflow_table(metas)` / `_build_workflows_json(metas)`**
- Columns: Name, Path, Agent count, Topology (parallel/for_each/pipeline).

**`_list_templates()` → `list[TemplateMeta]`**
- Discover template directories: `plugins/conductor-workflow-creator/assets/templates/` and any well-known user plugin paths.
- Parse YAML frontmatter comments for name and description.
- Return sorted list.

**`_print_deprecation_notice()`**
- Prints `[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]` to stderr.

### `app.py` — Deprecation Wrapper

The existing `conductor checkpoints` command is modified to:
1. Call `_print_deprecation_notice()` to stderr.
2. Delegate to `list_cmd._list_checkpoints_impl()`.

The `conductor registry list` command remains unchanged (it's part of the `registry` subcommand group, not deprecated).

---

## Infrastructure

| Component | Location | Port / Protocol | Notes |
|-----------|----------|----------------|-------|
| PID files | `~/.conductor/runs/*.pid` | N/A (filesystem) | JSON, one per running workflow |
| Event logs | `$TMPDIR/conductor/conductor-*.events.jsonl` | N/A (filesystem) | JSONL, one per run. Default `$TMPDIR` = `./tmp/` |
| Checkpoints | `$TMPDIR/conductor/checkpoints/*.json` | N/A (filesystem) | Managed by `CheckpointManager` |
| Registry config | `~/.conductor/registries.json` | N/A (filesystem) | Managed by `registry.config` |
| Templates | `plugins/conductor-workflow-creator/assets/templates/` | N/A (filesystem) | Built-in templates |
| Registry HTTP | GitHub API | 443 (HTTPS) | Existing `httpx` calls in `registry.github` |

**No new services, databases, caches, or ports.** Everything is local filesystem I/O.

---

## Key Technical Decisions

1. **Single new file (`list_cmd.py`).** All logic lives in one module to minimize surface area. The only change to existing code is the `app.add_typer(list_app)` registration line and the deprecation wrapper on the `checkpoints` command.

2. **Reuse existing primitives.** `read_pid_files()`, `CheckpointManager.list_checkpoints()`, `_list_all_registries()`, `_conductor_run_dir()` are imported and used directly — no new data access layers.

3. **Heuristic YAML filtering.** Rather than fully parsing every YAML file (expensive with Pydantic validation), do a cheap first-2-KB string search for `agents:`, `type: workflow`, or `runtime:`. Files without these keys are likely config files (e.g., `pyproject.toml`-adjacent YAML). The `--all` flag skips this filter.

4. **Event log parsing is defensive.** Each line is parsed individually; the first valid JSON line provides `started_at`, the last valid line provides `ended_at` and `status`. Truncated final lines are silently skipped. Files with zero valid JSON lines are skipped with a debug log.

5. **`--recent` cross-references PID files.** A JSONL file whose `run_id` matches an active PID file entry is shown as "running" — this avoids showing false "running" statuses for crashed runs whose event logs lack a terminal event.

6. **Rich tables to stdout (not stderr).** Unlike the existing `stop` and `registry` commands (which use `console` = stderr for verbosity control), `list` commands write tables to `output_console` (stdout) because their output IS the primary result, not diagnostic noise.

7. **No new dependencies.** Uses only `typer`, `rich`, `pyyaml`, `pathlib`, `json` — all already in `pyproject.toml`.

8. **Deprecation notices to stderr.** The old `conductor checkpoints` prints `[dim]` notice to stderr, preserving stdout compatibility for scripts that parse checkpoint output.

---

## Integration Points

### With Existing `cli/pid.py`
```python
from conductor.cli.pid import read_pid_files
entries = read_pid_files()
# entries: [{"pid": N, "port": N, "workflow": str, "started_at": str, 
#            "run_id": str, "log_file": str, "file": str}, ...]
```
Used by `list runs` for running workflow table and by `list summary` for the running count.

### With Existing `engine/checkpoint.py`
```python
from conductor.engine.checkpoint import CheckpointManager
checkpoints = CheckpointManager.list_checkpoints(workflow_path)
# checkpoints: list[CheckpointData]
```
Used by `list checkpoints` — identical to the existing `conductor checkpoints` implementation.

### With Existing `engine/event_log.py` and `engine/checkpoint.py` (shared helper)
```python
from conductor.engine.checkpoint import _conductor_run_dir
run_dir = _conductor_run_dir()  # Path("tmp") or CONDUCTOR_TMPDIR
logs = list(run_dir.glob("conductor-*.events.jsonl"))
```
Used by `list runs --recent` to discover event log files.

### With Existing `cli/registry.py`
```python
from conductor.cli.registry import _list_all_registries, _list_registry_workflows
# Directly call the existing functions — no subprocess spawning.
```
Used by `list registries` — directly calls `_list_all_registries()` and `_list_registry_workflows()` from `cli/registry.py`.

### With Existing `config/schema.py` and `config/loader.py`
```python
from conductor.config.loader import load_config
config = load_config(path)  # Full Pydantic parsing
# Only used when heuristic filter passes (not for every file).
```
Used by `list workflows` for extracting agent counts and topology tags after the cheap heuristic check passes.

### With `app.py` Registration

```python
# In app.py, after `app.add_typer(registry_app)`:
from conductor.cli.list_cmd import list_app
app.add_typer(list_app)

# Modify the existing checkpoints command:
@app.command(hidden=True)  # Make old command hidden
def checkpoints(...):
    """Deprecated — use 'conductor list checkpoints' instead."""
    console.print("[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]")
    from conductor.cli.list_cmd import _list_checkpoints_impl
    _list_checkpoints_impl(workflow)
```

### Deprecation of `checkpoints` Command

The existing `checkpoints` command at `app.py:983` is:
1. Marked `hidden=True` in the Typer decorator.
2. Modified to print `[dim]Deprecated: use 'conductor list checkpoints' instead[/dim]` to stderr via `console.print()`.
3. Delegates to a shared `_list_checkpoints_impl()` function in `list_cmd.py` that accepts `(workflow: Path | None)` and handles both Rich table and JSON output.

---

## Worker Boundaries

### cli-worker: `src/conductor/cli/list_cmd.py` (NEW)
Owns all `list` subcommand implementations:
- `list_summary` (callback)
- `list_runs` (command)
- `list_workflows` (command)
- `list_checkpoints` (command)
- `list_registries` (command)
- `list_templates` (command)
- Shared helpers: `_scan_event_logs`, `_discover_workflows`, `_heuristic_filter`, `_list_templates_from_dirs`, `_list_checkpoints_impl`
- JSON serialization helpers for each subcommand

### cli-worker: `src/conductor/cli/app.py` (MODIFIED)
- Register `list_app` Typer group: `app.add_typer(list_app)`
- Wrap existing `checkpoints` command with deprecation notice and delegation to `list_cmd.py`
- No other changes to `app.py`

### test-worker: `tests/test_cli/test_list.py` (NEW)
- Tests for every subcommand in both table and JSON modes
- Mock `read_pid_files()` for running workflow tests
- Mock event log files with valid/invalid JSON for recent runs
- Temp directories with YAML files for workflow discovery
- Tests for deprecation notice emission
- Tests for empty states, `--recent` truncation, `--all` flag, `--recursive` depth
