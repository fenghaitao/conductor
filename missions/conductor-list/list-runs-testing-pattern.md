## Testing `conductor list runs --recent`

Requires either (a) a real workflow run producing a genuine event log, or
(b) a simulated event log written via `_write_event_log()` helper. The simulation
approach is acceptable for unit/integration tests when LLM calls must be avoided.

Expected JSONL format: one JSON object per line, with `workflow_started` as the
first line and `workflow_completed`/`workflow_failed` as the last line.

`_conductor_run_dir()` and `read_pid_files()` must both be patched for the
command to see the simulated logs.

The event log format contract should be kept stable between the writer
(EventLogSubscriber) and reader (list_cmd._scan_event_logs) to prevent drift.
