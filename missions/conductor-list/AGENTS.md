# AGENTS.md — `conductor list` Mission

## Mission Boundaries

### Port Ranges
- **No new ports allocated.** `conductor list` is a read-only CLI command that prints to stdout and exits. It does not start any servers or daemons.
- Existing background workflow ports (as discovered via PID files at `~/.conductor/runs/*.pid`) are only read, never modified.

### Directories OFF-LIMITS
- `~/.conductor/runs/` — read PID files only; never write, delete, or rename.
- `$TMPDIR/conductor/` (default `./tmp/`) — read event logs (`*.events.jsonl`) and checkpoints (`checkpoints/*.json`) only; never create, modify, or delete.
- `~/.conductor/registries.json` — read-only through the existing `registry.config` module.
- The `src/conductor/engine/` directory — import only; no modifications.
- The `src/conductor/web/` directory — do not touch.
- The `src/conductor/providers/` directory — do not touch.

### External Services
- **GitHub API** (HTTPS port 443) — only accessed indirectly via the existing `conductor registry list` delegation. Do not add new HTTP calls in `list_cmd.py`.
- **No new network calls.** All local subcommands (`list`, `list runs`, `list workflows`, `list checkpoints`, `list templates`) are purely filesystem I/O.

### Git Rules
- **Commit to:** this repository (`/home/hfeng1/conductor`), on the current branch.
- **Do NOT:**
  - Add new dependencies to `pyproject.toml`. Use only `typer`, `rich`, `pyyaml`, `pathlib`, `json`, `logging` — all already present.
  - Modify files outside `src/conductor/cli/list_cmd.py` (create) and `src/conductor/cli/app.py` (minor registration + deprecation wrapper only).
  - Add new modules outside `src/conductor/cli/`.
  - Reformat or refactor existing code unrelated to the `list` feature.

---

## Worker Guidance

### Technology Choices (BINDING — no substitutions)

| Requirement | Choice |
|---|---|
| CLI framework | **Typer** (`typer.Typer` group + `@app.command()`) |
| Table output | **Rich** (`rich.table.Table`) via `output_console` (stdout) |
| Error/deprecation output | **Rich** via `console` (stderr) |
| YAML parsing | **PyYAML** (`yaml.safe_load`) |
| JSON output | **`json.dumps`** + `output_console.print_json()` |
| Config loading | **`conductor.config.loader.load_config`** (full Pydantic) — only after cheap heuristic passes |
| Filesystem walking | **`pathlib.Path.glob` / `Path.rglob`** (no `os.walk`) |
| PID discovery | **`conductor.cli.pid.read_pid_files()`** — import and use directly |
| Checkpoint listing | **`conductor.engine.checkpoint.CheckpointManager.list_checkpoints()`** — import and use directly |
| Run directory | **`conductor.engine.checkpoint._conductor_run_dir()`** — import and use directly |
| Registry listing | **`conductor.cli.registry._list_all_registries()`** and **`_list_registry_workflows()`** — call directly, no subprocess |

### Code Quality Standards

1. **Single new file.** All list subcommand logic lives in `src/conductor/cli/list_cmd.py`. No god files — but this feature's surface area is small enough that one file with clearly named internal helpers is correct. Do not split into `list_runs.py`, `list_workflows.py`, etc.

2. **Reuse, don't reimplement.** Import and call `read_pid_files()`, `CheckpointManager.list_checkpoints()`, `_conductor_run_dir()`, `_list_all_registries()`, `_list_registry_workflows()` directly. Do not copy-paste their internals.

3. **Stay in scope.** This mission delivers CLI commands. Do not:
   - Add fields to Pydantic schemas in `config/schema.py`.
   - Add methods to `CheckpointManager` or `EventLogSubscriber`.
   - Modify the web dashboard.
   - Change the workflow engine.
   - Add new environment variables.

4. **Defensive I/O.** All filesystem reads are wrapped in try/except. A corrupted PID file, truncated JSONL line, or unreadable YAML file is skipped with a `logger.debug()` or `logger.warning()` message — never crashes the command.

5. **Type hints required.** All functions must have full type annotations (`from __future__ import annotations`). Run `make typecheck` before committing.

6. **Google-style docstrings.** Every public function and helper gets a docstring.

### Commit Message Format

```
conductor list: <brief description>

<optional body with details>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### Reporting Pre-Existing Bugs

If you encounter a bug in existing code (e.g., a race in `read_pid_files`, a crash in `CheckpointManager`) that is NOT caused by your changes:

- **Do NOT fix it** in your changeset.
- **Document it** in the mission's issue tracker as a `non_blocking` note.
- Focus on the `list` feature only.

---

## Known Pre-Existing Issues
- Pre-existing: `_heuristic_filter` only handled `agents:` as a list (`isinstance(agents, list)`), but Conductor YAML uses dicts for named agent definitions. Fixed in this change to accept both `dict` and `list` forms.

*(None documented yet — orchestrator fills this in during the run.)*

---

## Testing & Validation Guidance

### Running Tests (scoped to this feature)

```bash
# Run only the list command tests
uv run pytest tests/test_cli/test_list.py -v

# Run with coverage for the new module
uv run pytest tests/test_cli/test_list.py --cov=conductor.cli.list_cmd --cov-report=term-missing

# Run all CLI tests (to catch regressions)
uv run pytest tests/test_cli/ -v
```

### Running Typecheck and Lint

```bash
# Type check (all code)
make typecheck

# Lint (all code)
make lint

# Auto-format before committing
make format
```

### Testing Tools Available

- **`typer.testing.CliRunner`** — for invoking CLI commands in-process. Use `CliRunner(mix_stderr=False)` so you can assert on stdout vs stderr independently.
- **`pytest.tmp_path`** — for creating temp directories with `.yaml` files, `.pid` files, and `.events.jsonl` files.
- **`unittest.mock.patch`** — for mocking `read_pid_files()`, `CheckpointManager.list_checkpoints()`, `_conductor_run_dir()`, and `_list_all_registries()`.
- **`json.loads`** — for validating `--json` output is well-formed JSON matching the documented schemas.

### Manual Testing

```bash
# Summary dashboard
uv run conductor list

# Running workflows (start a background workflow first if needed)
uv run conductor list runs

# Recent runs with JSON output
uv run conductor list runs --recent 5 --json

# Local workflow discovery
uv run conductor list workflows
uv run conductor list workflows --recursive --max-depth 2
uv run conductor list workflows --path examples/
uv run conductor list workflows --all

# Checkpoints (new path)
uv run conductor list checkpoints
uv run conductor list checkpoints examples/simple-qa.yaml --json

# Deprecated alias still works
uv run conductor checkpoints

# Registries
uv run conductor list registries
uv run conductor list registries <name>

# Templates
uv run conductor list templates --json
```

### Expected Output Contracts

| Subcommand | Default output | `--json` output | Exit 0 | Exit 1 |
|---|---|---|---|---|
| `conductor list` | Rich summary panel to stdout | N/A | Always | Only on unexpected crash |
| `list runs` | Rich table to stdout (columns: Port, PID, Workflow, Dashboard URL, Started) | JSON array of PID entries | Even with 0 running | Corrupted PID file (skip, not crash) |
| `list runs --recent N` | Rich table (adds: Status, Duration) | JSON array of RunHistoryEntry | Even with 0 log files | Corrupted log file (skip, not crash) |
| `list workflows` | Rich table to stdout (Name, Path, Agent count, Topology) | JSON array of WorkflowFileMeta | Even with 0 YAML files | Unreadable YAML (skip, not crash) |
| `list checkpoints` | Rich table to stdout | JSON array of CheckpointData | Even with 0 checkpoints | Corrupted checkpoint (skip, not crash) |
| `list registries` | Delegates to existing output | Delegates to existing output | Delegates | Delegates |
| `list templates` | Rich table to stdout (Name, Description, Path) | JSON array of TemplateMeta | Even with 0 templates | Missing template dir (skip gracefully) |
| `checkpoints` (deprecated) | Same as `list checkpoints` + `[dim]Deprecated: ...[/dim]` to stderr | Same | Same | Same |

---

## Implementation Order

1. **Create `src/conductor/cli/list_cmd.py`** with all subcommands and helpers.
2. **Register `list_app` in `src/conductor/cli/app.py`** (`app.add_typer(list_app)`).
3. **Wrap the deprecated `checkpoints` command** in `app.py` to print deprecation notice and delegate to `list_cmd._list_checkpoints_impl()`.
4. **Create `tests/test_cli/test_list.py`** with comprehensive tests.
5. **Run `make lint && make typecheck && make test`** to verify everything passes.

### YAML Parsing

- **ruamel.yaml** — The project uses `ruamel.yaml.YAML(typ='safe')` for all YAML parsing (not standard `yaml.safe_load`). New modules must use `ruamel.yaml` consistently: `from ruamel.yaml import YAML; from ruamel.yaml.error import YAMLError`. Do not import `yaml` from the standard library or PyYAML.
