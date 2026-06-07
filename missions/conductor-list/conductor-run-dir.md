# `_conductor_run_dir()` location

`_conductor_run_dir()` is defined in `conductor.engine.checkpoint` and returns the temp directory for conductor runtime artifacts (event logs, PID files, checkpoints). It resolves via `CONDUCTOR_TMPDIR` → `TMPDIR` → `cwd/tmp/`.

Import: `from conductor.engine.checkpoint import _conductor_run_dir`

Despite living in the checkpoint module, it is the canonical run-directory helper used by:
- `conductor.cli.run` — debug log file path resolution
- `conductor.cli.bg_runner` — background process log directory
- `conductor.engine.event_log` — JSONL event log path resolution
- `conductor.engine.checkpoint` — checkpoint directory resolution
- `conductor.cli.list_cmd` — event log discovery for `list runs`

Do not duplicate this logic; import and call the function directly.
