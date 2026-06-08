## Background Process Testing — Patch Target Paths

The CLI test helper `_invoke` in `tests/test_cli/test_list.py` uses
`CliRunner().invoke(app, args)` from typer. Mock patches for the background
lifecycle must target:

- `conductor.cli.bg_runner.launch_background` — for `run --web-bg`
- `conductor.cli.pid.read_pid_files` — for `list runs` + `stop`
- `conductor.cli.app.os.kill` — for stop's SIGTERM (patching `conductor.cli.app.os`
  works because `_stop_process` in `app.py` calls `os.kill()` via the module-level
  `import os`)
- `conductor.cli.pid.remove_pid_file` — for stop cleanup

These patch paths are non-obvious (especially `conductor.cli.app.os.kill` vs
`os.kill`) and documenting them avoids wasted debugging cycles.
