# AGENTS.md — conductor-list

## Mission Boundaries

### Port Ranges
**None.** This mission is purely read-only CLI — no ports are opened, no servers are started, no background processes are spawned. All data comes from local filesystem reads.

### Filesystem Boundaries

**Read-only access (DO NOT MODIFY):**
- `~/.conductor/runs/*.pid` — PID files for running workflows
- `$TMPDIR/conductor/conductor-*.events.jsonl` — event log files (default `$TMPDIR` = `./tmp/`)
- `$TMPDIR/conductor/checkpoints/*.json` — checkpoint files
- `~/.conductor/registries.json` — registry configuration
- `plugins/conductor-workflow-creator/assets/templates/` — built-in templates
- User's current working directory (for YAML discovery in `list workflows`)

**Files workers MAY create:**
- `src/conductor/cli/list_cmd.py` — NEW: all `list` subcommand implementations
- `tests/test_cli/test_list.py` — NEW: comprehensive CLI tests

**Files workers MAY modify:**
- `src/conductor/cli/app.py` — ONLY: register `list_app` Typer group + deprecation wrapper on `checkpoints` command

**Files that are OFF-LIMITS (do not touch):**
- `src/conductor/cli/pid.py` — existing PID file handling (import, don't modify)
- `src/conductor/engine/checkpoint.py` — existing checkpoint manager (import, don't modify)
- `src/conductor/engine/event_log.py` — existing event log subscriber (import, don't modify)
- `src/conductor/config/schema.py` — Pydantic models (import, don't modify)
- `src/conductor/config/loader.py` — YAML loader (import, don't modify)
- `src/conductor/cli/registry.py` — existing registry commands (import delegation functions, don't modify)
- `src/conductor/cli/run.py` — existing run command (import `_conductor_run_dir`, don't modify)
- `pyproject.toml` — no new dependencies to add
- `Makefile` — no new targets needed

### External Services
**None to modify.** This mission does not introduce any new external service dependencies. The only external interaction is the existing registry HTTP calls to GitHub API (port 443, read-only) — these are delegated to existing `cli/registry.py` functions and are NOT modified by this mission.

### Git Rules
- **Repository:** `fenghaitao/conductor` only. No commits to any other repos.
- **Branch:** Work on a feature branch off `main` (e.g., `feat/conductor-list`).
- **No force pushes** to `main` or shared branches.
- **Do NOT commit** any PID files, event logs, checkpoint files, or registry configs — these are user data.
- **Do NOT commit** `.pyc` files, `__pycache__`, or virtual environment directories.

---

## Worker Guidance

### Worker Types and Assignments

| Worker | File(s) | Scope |
|--------|---------|-------|
| **cli-worker** | `src/conductor/cli/list_cmd.py` (NEW), `src/conductor/cli/app.py` (MODIFIED) | All Typer subcommands, Rich table rendering, JSON output, deprecation wrapping |
| **test-worker** | `tests/test_cli/test_list.py` (NEW) | pytest tests covering all subcommands, both table and JSON output, empty states, edge cases |

### Binding Technology Choices (NO SUBSTITUTIONS)

- **CLI framework:** `typer` (already in pyproject.toml). Do NOT use `click`, `argparse`, or any other CLI library.
- **Output formatting:** `rich.table.Table` for table output, `json.dumps` for `--json` mode. Do NOT use `tabulate`, `prettytable`, or other table libraries.
- **YAML parsing:** `yaml.safe_load` (from PyYAML, already in pyproject.toml). Do NOT install `ruamel.yaml`.
- **File system:** `pathlib.Path` exclusively. Do NOT use `os.path`, `glob.glob`, or `shutil` for discovery.
- **PID data:** Import `read_pid_files` from `conductor.cli.pid`. Do NOT duplicate PID-reading logic.
- **Checkpoint data:** Import `CheckpointManager.list_checkpoints` from `conductor.engine.checkpoint`. Do NOT duplicate checkpoint-listing logic.
- **Registry data:** Import and call `_list_all_registries` and `_list_registry_workflows` from `conductor.cli.registry`. Do NOT spawn subprocesses or duplicate registry logic.
- **Event log path:** Import `_conductor_run_dir` from `conductor.engine.checkpoint`. Do NOT hardcode `tmp/` or `$TMPDIR`.
- **Runtime:** Python 3.12+. Use type hints throughout. Use `async/await` only if needed for registry delegation — all local subcommands are synchronous.

### Code Quality Standards

1. **No god files.** All list logic lives in `list_cmd.py`. If a helper function exceeds 50 lines or could be reused by multiple commands, extract it to a module-level private function prefixed with `_`.

2. **Stay in scope.** Do NOT:
   - Add new YAML schema fields to `config/schema.py`
   - Change dashboard behavior
   - Add new environment variables
   - Add new dependencies to `pyproject.toml`
   - Modify running workflows or event logs
   - Add a server, daemon, or background process
   - Change the `conductor stop` command or its output format

3. **Google-style docstrings** for all public functions and commands. Private helpers need at minimum a one-line docstring.

4. **Type hints required.** Every function signature must have type annotations for all parameters and return values. Use `from __future__ import annotations` if needed.

5. **Lint compliance.** Code must pass `make lint` (Ruff, line length 100). No `# noqa` comments without explicit justification.

6. **Type-check compliance.** Code must pass `make typecheck` (ty / Red Knot).

7. **Reuse existing primitives.** Do NOT reimplement PID parsing, checkpoint listing, registry listing, or event log path resolution. Import and call the existing functions.

8. **Defensive I/O.** All filesystem reads must be wrapped in try/except. A corrupted PID file or truncated event log line must be skipped with a debug log, never crashed.

### Commit Message Format

Use conventional commits:

```
feat(list): add runs subcommand with --recent and --json support

- Scans $TMPDIR/conductor/*.events.jsonl for recent run history
- Cross-references PID files to mark active runs as "running"
- Tolerates truncated event log lines gracefully

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

Prefixes: `feat(list):` for new subcommands, `fix(list):` for bug fixes, `test(list):` for test-only changes, `refactor(list):` for code restructuring.

### Reporting Pre-Existing Bugs

If you encounter a bug in existing code (files you are NOT modifying), do NOT fix it in this mission. Instead, report it:

- Add an entry to `discoveredIssues` in the mission tracking document with: file path, line number (if known), symptom, and reproduction steps.
- Mark as `non_blocking` unless it directly prevents implementing `list` functionality.
- Example: "`pid.read_pid_files()` returns stale entries for killed processes — non_blocking, `list runs` will show them as running unless the PID is checked."

---

## Known Pre-Existing Issues

*(None reported at mission start. Workers: add discovered issues here as encountered.)*

---

## Testing & Validation Guidance

### Running Tests

```bash
# Run all tests (ensures no regressions)
make test

# Run only list-related tests
uv run pytest tests/test_cli/test_list.py -v

# Run a specific test by pattern
uv run pytest tests/test_cli/test_list.py -k "test_list_runs" -v

# Run with coverage
make test-cov
```

### Linting and Type Checking

```bash
# Lint check (must pass — no new violations)
make lint

# Auto-fix lint issues
make format

# Type check (must pass)
make typecheck

# Run all checks
make check
```

### Testing Tools

- **`typer.testing.CliRunner`** — Use for all CLI tests. Invoke `app` directly (no subprocess).
- **`pytest` fixtures** — Use `tmp_path` for temporary files, `monkeypatch` for mocking environment variables and `read_pid_files()`.
- **`unittest.mock.patch`** — Mock `read_pid_files()`, `CheckpointManager.list_checkpoints()`, and `_conductor_run_dir()` for unit tests.

### Test Coverage Requirements

Each subcommand must have tests for:

| Scenario | `list` | `runs` | `workflows` | `checkpoints` | `registries` | `templates` |
|----------|--------|--------|-------------|---------------|--------------|-------------|
| Table output (default) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| JSON output (`--json`) | N/A | ✅ | ✅ | ✅ | N/A | ✅ |
| Empty state (no data) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Single entry | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Multiple entries | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `--recent` truncation | N/A | ✅ | N/A | N/A | N/A | N/A |
| `--recursive` / `--max-depth` | N/A | N/A | ✅ | N/A | N/A | N/A |
| `--all` flag | N/A | N/A | ✅ | N/A | N/A | N/A |
| Heuristic filtering accuracy | N/A | N/A | ✅ | N/A | N/A | N/A |
| Deprecation notice (stderr) | N/A | N/A | N/A | ✅ | N/A | N/A |
| JSON schema stability | N/A | ✅ | ✅ | ✅ | N/A | ✅ |
| Corrupted file tolerance | N/A | ✅ | ✅ | N/A | N/A | N/A |

### Manual Validation

```bash
# Smoke test: summary dashboard
uv run conductor list

# Smoke test: list running workflows (may be empty)
uv run conductor list runs

# Smoke test: list runs with recent history (may be empty if no prior runs)
uv run conductor list runs --recent 10

# Smoke test: list runs as JSON
uv run conductor list runs --json | python -m json.tool

# Smoke test: discover workflow YAML files
uv run conductor list workflows
uv run conductor list workflows --recursive
uv run conductor list workflows --path examples/

# Smoke test: list checkpoints (both old and new commands)
uv run conductor checkpoints
uv run conductor list checkpoints

# Smoke test: list registries
uv run conductor list registries

# Smoke test: list templates
uv run conductor list templates

# Verify deprecation notice goes to stderr
uv run conductor checkpoints 2>&1 >/dev/null | grep -i deprecated

# Verify --help shows list group
uv run conductor --help | grep -A5 list
```

### Exit Code Contract

- Exit code 0 on success (including empty results).
- Exit code 1 on errors (unreadable event log, missing directory).
- An empty result (no running workflows, no YAML files found) is NOT an error — exit 0 with a dim "nothing found" message.