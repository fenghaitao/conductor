# conductor-list

# Mission Proposal: `conductor list`

## Plan Overview

Add a `conductor list` subcommand group that provides unified discovery of running
workflows, recent runs, available workflow YAML files, checkpoints, and
registry-published workflows. Today users must cobble together `conductor stop`
(no-args) to see running workflows, `conductor checkpoints` for checkpoint
listings, and `conductor registry list` for registry workflows — there is no way
to discover local `.yaml` workflow files or to see recent run history short of
manually inspecting `$TMPDIR/conductor/` event logs.

**Complete user journey:**

1. `conductor list` — shows a summary dashboard: count of running workflows,
   recent completed runs, available local workflows, and pinned registries.
2. `conductor list runs` — table of running background workflows (port, PID,
   workflow name, dashboard URL, uptime) plus optional `--recent N` to show the
   last N completed/failed runs from event logs.
3. `conductor list workflows` — discovers `*.yaml` / `*.yml` files in the
   current directory (recursive, configurable depth), filtering out non-workflow
   YAML with a heuristic that checks for `agents:` or `type: workflow` keys.
4. `conductor list checkpoints` — existing `conductor checkpoints` command
   moved under the `list` group; old top-level command preserved as a deprecated
   alias.
5. `conductor list registries` — delegates to existing `conductor registry
   list`; also a deprecated alias kept for compatibility.
6. `conductor list templates` — lists built-in and plugin-provided workflow
   templates with name, description, and path.

All subcommands use Rich tables for output with `--json` flag to emit
machine-readable JSON for scripting and CI integration.

## Expected Functionality

### M1: Core CLI scaffold and `list runs`

- **`conductor list` (no subcommand)** — Print a summary panel with counts:
  running workflows, recent runs (last 24h), local workflow files found,
  configured registries, available templates. Each count is accompanied by a
  hint for the full subcommand (`conductor list runs`, etc.).
- **`conductor list runs`** — Reuse `pid.read_pid_files()` to display a Rich
  table of running background workflows with columns: Port, PID, Workflow,
  Dashboard URL, Started. Empty-state message when nothing is running.
- **`conductor list runs --recent N`** — Scan `$TMPDIR/conductor/*.events.jsonl`
  files, parse the first and last events from each to derive: workflow name, run
  id, start time, end time (or "running"), status (completed/failed/running),
  duration. Sort by start time descending, limit to N.
- **`conductor list runs --json`** — Output the same data as a JSON array to
  stdout for programmatic consumption.

### M2: `list workflows` (local discovery)

- **`conductor list workflows`** — Walk the current directory (non-recursive by
  default) for `*.yaml` and `*.yml` files, inspect each for `agents:` or `type:
  workflow` top-level keys to filter out config files, and display a table:
  Name (stem), Path, Agent count, Topology tags (parallel, for_each, pipeline).
- **`conductor list workflows --recursive`** — Walk subdirectories up to
  `--max-depth` (default 3).
- **`conductor list workflows --path <dir>`** — Start search from a specific
  directory instead of cwd.
- **`conductor list workflows --json`** — JSON output with full paths and
  parsed metadata.
- **Heuristic filtering** — Quick YAML front-matter scan (first 1 KB) for
  `agents:`, `type: workflow`, `runtime:`. Files without these are excluded with
  a `--all` escape hatch to show everything.

### M3: `list checkpoints` and `list registries` (unification)

- **`conductor list checkpoints`** — Drop-in replacement for `conductor
  checkpoints`. Same args (`[WORKFLOW]`), same Rich table output, same filtering
  logic. The old top-level `checkpoints` command becomes a hidden alias that
  prints a deprecation notice to stderr and delegates to `list checkpoints`.
- **`conductor list checkpoints --json`** — JSON array output.
- **`conductor list registries`** — Delegates to existing `conductor registry
  list`. Old `registry list` preserved as-is.
- **`conductor list registries <name>`** — Lists workflows in a specific
  registry (delegates to existing `conductor registry list <name>`).

### M4: `list templates`

- **`conductor list templates`** — Enumerate templates from the built-in
  `plugins/conductor-workflow-creator/assets/templates/` directory (and any
  user/plugin template directories discovered via a well-known path convention).
  Display: Name, Description, Path.
- **`conductor list templates --json`** — JSON output.

### M5: `--json` flag and scripting contract

- Every `list` subcommand supports `--json` which emits a JSON array of objects
  to stdout (not stderr). Rich table output goes to stdout by default as well.
- JSON schema is stable: each subcommand documents its output fields.
- Exit code 0 on success, 1 on errors (e.g., unreadable event log, missing
  directory).

### M6: Deprecation notices and migration

- `conductor checkpoints` prints `[dim]Deprecated: use `conductor list
  checkpoints` instead[/dim]` to stderr before executing.
- `conductor registry list` is preserved without deprecation (it belongs to the
  `registry` subcommand group).
- Both old commands remain functional for at least 2 minor releases.

## Environment Setup

- **No new dependencies** — `conductor list` uses only packages already in
  `pyproject.toml`: `typer`, `rich`, `pyyaml`.
- **No new environment variables required.**
- **No credentials or external services needed** — all data comes from local
  filesystem (`~/.conductor/runs/*.pid`, `$TMPDIR/conductor/*.events.jsonl`,
  `~/.conductor/checkpoints/*.json`, `~/.conductor/registries.json`) and the
  current working directory.
- **Event log directory** uses the same `_conductor_run_dir()` helper
  (`$TMPDIR/conductor/`) already used by `EventLogSubscriber`.

## Infrastructure

- **No new services, databases, caches, or queues.** Everything is filesystem
  I/O.
- **No new ports.** `conductor list` is a read-only CLI command that prints to
  stdout and exits.
- **Process boundary:** `conductor list` runs in-process with no subprocess
  spawning (except for the existing registry commands when listing remote
  registries, which already use `httpx`).
- **Mission boundaries:**
  - **In scope:** Filesystem scanning, PID file parsing, event log parsing,
    YAML heuristic inspection, Rich table rendering, JSON output, deprecation
    aliases.
  - **Out of scope:** Modifying any running workflows, starting/stopping
    workflows, modifying event logs or checkpoints, adding a server or daemon,
    changing the dashboard, adding new YAML schema fields.

## Worker Types

- **cli-worker:** Implements Typer subcommands in `src/conductor/cli/list_cmd.py`
  (new file) and registers them in `app.py`. Uses `rich.table.Table` for
  formatted output, `json.dumps` for `--json` mode, `pid.read_pid_files()` for
  running workflow discovery, `pathlib.Path.glob` for local workflow discovery,
  `yaml.safe_load` for heuristic YAML inspection, and `conductor.engine.checkpoint`
  for checkpoint listing. Also handles deprecation notices by wrapping old
  commands.

- **test-worker:** Writes pytest tests in `tests/test_cli/test_list.py` covering:
  all subcommand output formats (table + JSON), empty states, `--recent`
  filtering, recursive workflow discovery, heuristic filtering accuracy,
  deprecation notice emission, and JSON schema stability.

## Testing & Validation Strategy

- **CLI surface:** `uv run conductor list`, `uv run conductor list runs`,
  `uv run conductor list runs --recent 5 --json`, etc. Tested via
  `typer.testing.CliRunner` in pytest.
- **Unit tests** (`tests/test_cli/test_list.py`):
  - Mock `read_pid_files()` to return 0, 1, and 3 entries; assert table rows
    and JSON output.
  - Create temp directories with `.yaml` files (some valid workflows, some
    non-workflow configs); assert heuristic filtering and `--all` behavior.
  - Mock event log files with 0, 1, and many runs; assert `--recent`
    truncation and status derivation.
  - Assert `conductor checkpoints` still works but emits deprecation stderr.
  - Assert JSON output is valid and stable across versions.
- **Programmatic validators:**
  - `make lint` (ruff) — no new lint violations.
  - `make typecheck` (ty) — all new code type-annotated.
  - `make test` — all existing tests continue to pass.

## Non-Functional Requirements

- **Performance:**
  - `conductor list` (summary) completes in < 100 ms on a warm filesystem.
  - `conductor list runs --recent 50` completes in < 500 ms for up to 200 event
    log files.
  - `conductor list workflows --recursive` completes in < 1 s for directories
    with up to 500 YAML files.
  - YAML heuristic scan reads at most the first 2 KB per file.

- **Security:**
  - No file writes, no process spawning (outside registry HTTP), no network
    calls for local subcommands.
  - Event log and PID file parsing uses try/except guards against malformed
    files — a corrupted file is skipped with a debug log, never crashes the
    command.

- **Reliability:**
  - All filesystem operations are read-only and tolerate missing
    files/directories gracefully with empty results, not errors.
  - `conductor list runs` tolerates partially-written event logs (truncated
    last line) by parsing line-by-line and discarding invalid JSON lines.

- **Backward compatibility:**
  - Existing `conductor checkpoints` and `conductor registry list` continue to
    work unchanged (with deprecation notice for checkpoints).
  - New `conductor list` group does not shadow any existing top-level command.
  - `conductor --help` shows the new `list` group in the command listing.
