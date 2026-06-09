## Testing `conductor list` Subcommands

- Use `CliRunner.invoke()` on the Typer app directly via the `_invoke()` helper
  defined at line 29 of `tests/test_cli/test_list.py`.
- For workflow discovery tests, create temp directories with valid/invalid YAML
  files using `tmp_path`.
- For run history tests, simulate event log JSONL files and patch
  `_conductor_run_dir()` to point at the temp directory — no actual workflow
  execution is needed for read-only listing commands.
- For background lifecycle tests, target mock patches at
  `conductor.cli.bg_runner.launch_background`, `conductor.cli.pid.read_pid_files`,
  `conductor.cli.app.os.kill`, and `conductor.cli.pid.remove_pid_file`.


## Accumulated Worker Feedback

These deviations were reported by workers during the mission.
Review and incorporate into the procedure above as appropriate.

- Step `Step 2: Test First (TDD)`: Tests were written against an already-implemented list_cmd.py. The conductor init --template command does not exist, so template instantiation is simulated via shutil.copy2. (reason: The init command was removed during the registry redesign. The test validates the cross-command flow using the available CLI surface.)

- Step `Step 2: Test First (TDD)`: Tests were written against an already-implemented list_cmd.py. The conductor init --template command does not exist, so template instantiation is simulated via shutil.copy2.
- Step `Step 2: Test First (TDD)`: Tests were written against an already-implemented list_cmd.py. The conductor init --template command does not exist, so template instantiation is simulated via shutil.copy2.