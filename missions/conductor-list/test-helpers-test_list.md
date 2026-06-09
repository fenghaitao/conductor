## Reusable Test Helpers in test_list.py

- `_make_checkpoint_data()` (line 3328): Constructs real `CheckpointData` objects
  for mocking — reusable pattern for any test needing checkpoint data.
- `_invoke()` (line 29): Thin `CliRunner.invoke` wrapper.
- `_write_event_log()`: Writes simulated event log JSONL files to a temp directory.

All are module-level helpers available for other test files that need to mock
checkpoints, invoke CLI commands, or simulate event logs.
