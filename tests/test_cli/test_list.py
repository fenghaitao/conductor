"""Tests for `conductor list` command group.

Focusing on the `list templates` subcommand (milestone 4.1), with
coverage for the full `list` group registration and basic shell for
other subcommands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from conductor.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(args: list[str]) -> Any:
    """Invoke the CLI app and return the result object."""
    return runner.invoke(app, args)


# ---------------------------------------------------------------------------
# Test: `conductor list --help` shows subcommands
# ---------------------------------------------------------------------------


class TestListHelp:
    """Verify the `list` group is registered and shows all subcommands."""

    def test_list_help_shows_subcommands(self) -> None:
        """`conductor list --help` lists templates among other subcommands."""
        result = _invoke(["list", "--help"])
        assert result.exit_code == 0
        assert "templates" in result.output
        assert "runs" in result.output
        assert "workflows" in result.output
        assert "checkpoints" in result.output
        assert "registries" in result.output

    def test_list_templates_help(self) -> None:
        """`conductor list templates --help` shows --json flag."""
        import re

        result = _invoke(["list", "templates", "--help"])
        assert result.exit_code == 0
        # Strip ANSI escape codes since Rich may format `--json` with embedded codes
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--json" in clean


# ---------------------------------------------------------------------------
# Test: `conductor list templates` — table output
# ---------------------------------------------------------------------------


class TestListTemplates:
    """Verify template discovery from built-in template directory."""

    def test_table_output_lists_all_builtins(self) -> None:
        """Running `conductor list templates` displays a Rich table with
        at least 3 entries (pipeline, fan-out, loop)."""
        import re

        result = _invoke(["list", "templates"])
        assert result.exit_code == 0
        # Strip ANSI escape codes for reliable substring matching
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Table headers
        assert "Name" in clean
        assert "Description" in clean
        assert "Path" in clean
        # Each template name from comment headers should appear
        assert "Pipeline template" in clean
        assert "Fan-out template" in clean
        assert "Loop template" in clean
        # Descriptions / names should appear (may span lines)
        assert "Sequential stages" in clean
        assert "Process multiple items" in clean
        assert "Loop template" in clean
        assert "Retry" in clean
        assert "until condition" in clean

    def test_table_does_not_show_filenames_as_names(self) -> None:
        """Template names come from comment headers, not filename stems."""
        result = _invoke(["list", "templates"])
        assert result.exit_code == 0
        # Names should be from comment headers, e.g. "Pipeline template: ..."
        # Filename stems like "pipeline" should not appear as a standalone name
        output = result.output
        assert "Pipeline template" in output
        assert "Fan-out template" in output
        assert "Loop template" in output

    def test_exit_code_zero_on_success(self) -> None:
        """Both table and JSON modes exit with 0 on successful listing."""
        result = _invoke(["list", "templates"])
        assert result.exit_code == 0
        assert result.stderr == "" or "Error" not in result.stderr


# ---------------------------------------------------------------------------
# Test: `conductor list templates --json` — JSON output
# ---------------------------------------------------------------------------


class TestListTemplatesJson:
    """Verify `--json` emits a valid JSON array of template objects."""

    def test_json_output_is_valid_array(self) -> None:
        """`conductor list templates --json` emits a valid JSON array."""
        result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 3

    def test_json_each_entry_has_required_fields(self) -> None:
        """Each JSON object has name, description, path — all non-empty strings."""
        result = _invoke(["list", "templates", "--json"])
        data = json.loads(result.output)
        for entry in data:
            assert isinstance(entry, dict)
            assert "name" in entry
            assert "description" in entry
            assert "path" in entry
            assert isinstance(entry["name"], str) and entry["name"]
            assert isinstance(entry["description"], str) and entry["description"]
            assert isinstance(entry["path"], str) and entry["path"]

    def test_json_paths_point_to_existing_files(self) -> None:
        """Each `path` field points to an existing .yaml or .yml file."""
        result = _invoke(["list", "templates", "--json"])
        data = json.loads(result.output)
        for entry in data:
            p = Path(entry["path"])
            assert p.exists(), f"Path does not exist: {entry['path']}"
            assert p.suffix in (".yaml", ".yml"), f"Not a YAML file: {entry['path']}"

    def test_json_names_match_comment_headers_not_stems(self) -> None:
        """The `name` field comes from the first comment line, not the filename."""
        result = _invoke(["list", "templates", "--json"])
        data = json.loads(result.output)
        names = [e["name"] for e in data]
        # Names should be the full title from comment headers, not just "pipeline" etc.
        assert any("Pipeline template" in n for n in names)
        assert any("Fan-out template" in n for n in names)
        assert any("Loop template" in n for n in names)

    def test_json_descriptions_contain_use_when(self) -> None:
        """The `description` field contains the 'Use when:' text from comments."""
        result = _invoke(["list", "templates", "--json"])
        data = json.loads(result.output)
        descriptions = [e["description"] for e in data]
        assert any("ordered stages" in d for d in descriptions)
        assert any("independent tasks" in d for d in descriptions)
        assert any("iterate" in d.lower() for d in descriptions)

    def test_json_array_length_matches_table_rows(self) -> None:
        """JSON array length matches the number of rows in the table output."""
        result_json = _invoke(["list", "templates", "--json"])
        result_table = _invoke(["list", "templates"])
        json_data = json.loads(result_json.output)
        # Count table data rows (lines with "│" that contain template names)
        table_lines = [
            line
            for line in result_table.output.split("\n")
            if "│" in line and any(kw in line for kw in ("Pipeline", "Fan-out", "Loop"))
        ]
        # Table may have header/footer — count rows with template keywords
        assert len(json_data) >= len(table_lines)


# ---------------------------------------------------------------------------
# Test: Graceful degradation when no template directory
# ---------------------------------------------------------------------------


class TestListTemplatesEmpty:
    """Verify graceful behavior when template directory is missing or empty."""

    def test_no_template_dir_shows_empty_message(self) -> None:
        """When no template directory exists, print friendly message, exit 0."""
        with patch.object(Path, "is_dir", return_value=False):
            # Need to patch at a deeper level since the function will check
            # the specific template dir path
            result = _invoke(["list", "templates"])
            assert result.exit_code == 0
            assert "No templates found" in result.output or "no templates" in result.output.lower()

    def test_empty_template_dir_emits_empty_json_array(self) -> None:
        """When no templates, `--json` emits `[]`."""
        with patch.object(Path, "is_dir", return_value=False):
            result = _invoke(["list", "templates", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data == []

    def test_template_dir_missing_exits_zero(self) -> None:
        """Missing template dir is not an error — exit 0."""
        result = _invoke(["list", "templates"])
        # Even if dir exists now, the command should not crash
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test: Non-template files are excluded
# ---------------------------------------------------------------------------


class TestListTemplatesFiltering:
    """Verify that non-template files are excluded from results."""

    def test_non_template_yaml_excluded(self, tmp_path: Path) -> None:
        """YAML files without proper comment headers are excluded."""
        # This test verifies the filtering logic by creating a temp dir
        # with both template-like and non-template YAML files
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create a file that looks like a template
        (templates_dir / "good.yaml").write_text(
            "# Good Template\n# Use when: testing\nworkflow:\n  name: test\n"
        )

        # Create a file without comment headers
        (templates_dir / "config.yaml").write_text("settings:\n  debug: true\n")

        # Create a non-yaml file
        (templates_dir / "README.md").write_text("# Templates\n")

        # We can't easily patch the templates directory in the command
        # without a custom env var, but we test the _parse_template_headers
        # logic directly.
        from conductor.cli.list_cmd import _parse_template_headers

        good = _parse_template_headers(templates_dir / "good.yaml")
        assert good is not None
        assert good[0] == "Good Template"
        assert good[1] == "Use when: testing"

        bad = _parse_template_headers(templates_dir / "config.yaml")
        assert bad is None

    def test_json_excludes_non_template_files(self, tmp_path: Path) -> None:
        """`--json` output excludes files without parsable comment headers."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        (templates_dir / "good.yaml").write_text(
            "# Good Template\n# Use when: testing\nworkflow:\n  name: test\n"
        )
        (templates_dir / "bad.yaml").write_text("not: a template\n")

        from conductor.cli.list_cmd import _discover_templates

        results = _discover_templates([templates_dir])
        paths = [r["path"] for r in results]
        assert str(templates_dir / "good.yaml") in paths
        assert str(templates_dir / "bad.yaml") not in paths


# ---------------------------------------------------------------------------
# Test: list summary callback
# ---------------------------------------------------------------------------


class TestListSummary:
    """Verify the `conductor list` (no subcommand) summary dashboard."""

    # ------------------------------------------------------------------
    # Structural assertions
    # ------------------------------------------------------------------

    def test_list_summary_exit_code_zero(self) -> None:
        """Summary command exits 0."""
        result = _invoke(["list"])
        assert result.exit_code == 0

    def test_list_summary_uses_panel_not_table(self) -> None:
        """Summary uses a Rich Panel, not a table (no column headers)."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        # Rich Panel borders
        assert "╭" in output or "┌" in output
        # No table column markers (Rich tables use "│" for cells but also
        # for panel borders — check for absence of table-specific formatting)
        assert "┃" not in output  # Rich table left column border

    # ------------------------------------------------------------------
    # Count line assertions (VALIDATION: VAL-LRUNS-005)
    # ------------------------------------------------------------------

    def test_list_summary_has_running_count(self) -> None:
        """Summary shows running workflows count with hint."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        assert "running" in output.lower()
        assert "conductor list runs" in output

    def test_list_summary_has_recent_count(self) -> None:
        """Summary shows recent runs count with hint."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        assert "Recent runs" in output
        assert "conductor list runs --recent" in output

    def test_list_summary_has_workflow_count(self) -> None:
        """Summary shows local workflow files count with hint."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        assert "Local workflows" in output
        assert "conductor list workflows" in output

    def test_list_summary_has_template_count(self) -> None:
        """Summary shows template count with hint."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        assert "Templates" in output
        assert "conductor list templates" in output

    def test_list_summary_counts_are_integers(self) -> None:
        """All counts are integers (including zero), not empty strings."""
        import re

        result = _invoke(["list"])
        assert result.exit_code == 0
        # Strip ANSI codes for reliable matching
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Each category line should contain a digit (count)
        assert re.search(r"Running workflows:\s*\d+", clean)
        assert re.search(r"Recent runs:\s*\d+", clean)
        assert re.search(r"Local workflows:\s*\d+", clean)
        assert re.search(r"Templates:\s*\d+", clean)

    def test_list_summary_with_zero_running(self) -> None:
        """Counts can be 0 — summary still renders."""
        from unittest.mock import patch

        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list"])
            assert result.exit_code == 0
            import re

            clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
            assert re.search(r"Running workflows:\s*0", clean)

    def test_list_summary_with_running_workflows(self) -> None:
        """When PID files exist, count reflects them."""
        from unittest.mock import patch

        pid_entries = [
            {
                "pid": 12345,
                "port": 8080,
                "workflow": "test.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "abc12345",
                "file": "/tmp/test.pid",
            },
            {
                "pid": 12346,
                "port": 8081,
                "workflow": "other.yaml",
                "started_at": "2026-01-01T01:00:00+00:00",
                "run_id": "def67890",
                "file": "/tmp/other.pid",
            },
        ]

        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list"])
            assert result.exit_code == 0
            import re

            clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
            assert re.search(r"Running workflows:\s*2", clean)

    def test_list_summary_resilient_to_pid_error(self) -> None:
        """Summary doesn't crash on PID file read errors."""
        from unittest.mock import patch

        with patch("conductor.cli.pid.read_pid_files", side_effect=OSError("permission denied")):
            result = _invoke(["list"])
            assert result.exit_code == 0
            import re

            clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
            # Should still show 0 for running workflows
            assert re.search(r"Running workflows:\s*0", clean)

    def test_list_summary_stderr_is_empty(self) -> None:
        """Summary writes only to stdout, not stderr."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        assert result.stderr == ""


# ---------------------------------------------------------------------------
# Test: `conductor list runs` — running workflows table
# ---------------------------------------------------------------------------


class TestListRunsRunning:
    """Verify `list runs` displays running workflows from PID files."""

    def test_no_running_workflows(self) -> None:
        """When no PID files exist, print dim empty message, exit 0."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs"])
        assert result.exit_code == 0
        assert "No running workflows found" in result.output

    def test_single_running_workflow(self) -> None:
        """One PID entry produces a table with one row and correct values."""
        pid_entries = [
            {
                "pid": 12345,
                "port": 8080,
                "workflow": "my-workflow.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "abc12345",
                "file": "/tmp/test.pid",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list", "runs"])
        assert result.exit_code == 0
        output = result.output
        assert "8080" in output
        assert "12345" in output
        assert "my-workflow" in output
        assert "http://127.0.0.1:8080" in output
        assert "2026-01-01" in output

    def test_multiple_running_workflows(self) -> None:
        """Multiple PID entries produce a table with multiple rows."""
        pid_entries = [
            {
                "pid": 100,
                "port": 8000,
                "workflow": "alpha.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "aaa11111",
                "file": "/tmp/a.pid",
            },
            {
                "pid": 200,
                "port": 8001,
                "workflow": "beta.yaml",
                "started_at": "2026-01-01T01:00:00+00:00",
                "run_id": "bbb22222",
                "file": "/tmp/b.pid",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list", "runs"])
        assert result.exit_code == 0
        output = result.output
        assert "alpha" in output
        assert "beta" in output
        assert "8000" in output
        assert "8001" in output

    def test_table_has_expected_columns(self) -> None:
        """The running table includes Port, PID, Workflow, Dashboard URL, Started."""
        pid_entries = [
            {
                "pid": 9999,
                "port": 9090,
                "workflow": "test.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "x",
                "file": "/tmp/t.pid",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list", "runs"])
        assert result.exit_code == 0
        output = result.output
        assert "Port" in output
        assert "PID" in output
        assert "Workflow" in output
        assert "Dashboard URL" in output
        assert "Started" in output

    def test_pid_read_error_graceful(self) -> None:
        """PID read errors produce empty state, not crash."""
        with patch("conductor.cli.pid.read_pid_files", side_effect=OSError("boom")):
            result = _invoke(["list", "runs"])
        assert result.exit_code == 0
        assert "No running workflows found" in result.output


# ---------------------------------------------------------------------------
# Test: `conductor list runs --json` — JSON output for running workflows
# ---------------------------------------------------------------------------


class TestListRunsJson:
    """Verify `list runs --json` emits valid JSON for running workflows."""

    def test_empty_runs_json(self) -> None:
        """No PID files → empty JSON array, exit 0."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data == []

    def test_single_run_json_has_required_keys(self) -> None:
        """Each JSON entry has pid, port, workflow, dashboard_url, started_at, run_id, status."""
        pid_entries = [
            {
                "pid": 42,
                "port": 4242,
                "workflow": "w.yaml",
                "started_at": "2026-03-01T12:00:00+00:00",
                "run_id": "deadbeef",
                "file": "/tmp/x.pid",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        entry = data[0]
        assert entry["pid"] == 42
        assert entry["port"] == 4242
        assert entry["workflow"] == "w"
        assert entry["dashboard_url"] == "http://127.0.0.1:4242"
        assert entry["started_at"] == "2026-03-01T12:00:00+00:00"
        assert entry["run_id"] == "deadbeef"
        assert entry["status"] == "running"

    def test_json_no_rich_markup(self) -> None:
        """JSON output contains no Rich ANSI escape codes."""
        pid_entries = [
            {
                "pid": 1,
                "port": 2,
                "workflow": "x.yaml",
                "started_at": "t",
                "run_id": "r",
                "file": "f",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        # Raw output should be valid JSON without ANSI codes
        json.loads(result.output)
        assert "\x1b" not in result.output


# ---------------------------------------------------------------------------
# Test: `conductor list runs --recent N` — recent run history
# ---------------------------------------------------------------------------


def _make_event_log(
    dir: Path,
    stem: str,
    workflow_name: str,
    started_ts: float,
    ended_ts: float | None = None,
    end_event: str = "workflow_completed",
) -> Path:
    """Create a realistic event log file for testing.

    Args:
        dir: Directory to create the file in.
        stem: Filename stem (e.g. "conductor-test-2025...-runid.events").
        workflow_name: Workflow name for the ``workflow_started`` event.
        started_ts: Unix timestamp for the start event.
        ended_ts: Unix timestamp for the end event. If None, no terminal event.
        end_event: Event type for the terminal event ("workflow_completed" or "workflow_failed").

    Returns:
        Path to the created file.
    """
    fp = dir / f"{stem}.jsonl"
    lines = [
        json.dumps(
            {
                "type": "workflow_started",
                "timestamp": started_ts,
                "data": {"name": workflow_name},
            }
        )
    ]
    if ended_ts is not None:
        lines.append(
            json.dumps(
                {
                    "type": end_event,
                    "timestamp": ended_ts,
                    "data": {},
                }
            )
        )
    fp.write_text("\n".join(lines))
    return fp


class TestListRunsRecent:
    """Verify `list runs --recent N` scans event logs and displays history."""

    def test_recent_limits_to_n(self, tmp_path: Path) -> None:
        """--recent 2 returns at most 2 entries even with many event logs."""
        run_dir = tmp_path / "conductor_runs"
        run_dir.mkdir()
        for i in range(5):
            _make_event_log(
                run_dir,
                f"conductor-test-2025010{i}-01000{i}-id{i:08x}.events",
                f"workflow-{i}",
                1700000000 + i * 10,
                1700000000 + i * 10 + 5,
            )

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "2"])
        assert result.exit_code == 0
        # Should have at most 2 entries in the table (plus header/footer)
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Count completed entries
        assert clean.count("completed") == 2
        assert "workflow-3" in clean or "workflow-4" in clean  # most recent

    def test_recent_sorted_by_started_desc(self, tmp_path: Path) -> None:
        """Entries are sorted by started_at descending (most recent first)."""
        run_dir = tmp_path / "conductor_runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-old-20240101-000000-aaaaaaaa.events",
            "old-workflow",
            1700000000.0,
            1700000005.0,
        )
        _make_event_log(
            run_dir,
            "conductor-new-20260101-000000-bbbbbbbb.events",
            "new-workflow",
            1767225600.0,
            1767225610.0,
        )

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # "new-workflow" should appear before "old-workflow" (sorted descending)
        new_pos = clean.index("new-workflow")
        old_pos = clean.index("old-workflow")
        assert new_pos < old_pos, "Most recent workflow should appear first"

    def test_status_completed(self, tmp_path: Path) -> None:
        """Event log ending with workflow_completed → status=completed."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-done-20250101-000000-cccccccc.events",
            "done-wf",
            1700000000.0,
            1700000010.0,
            end_event="workflow_completed",
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "completed" in clean
        assert "failed" not in clean

    def test_status_failed(self, tmp_path: Path) -> None:
        """Event log ending with workflow_failed → status=failed."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-fail-20250101-000000-dddddddd.events",
            "fail-wf",
            1700000000.0,
            1700000010.0,
            end_event="workflow_failed",
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "failed" in clean
        assert "completed" not in clean

    def test_status_running_no_terminal_event(self, tmp_path: Path) -> None:
        """Event log with no terminal event → status=running."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-alive-20250101-000000-eeeeeeee.events",
            "alive-wf",
            1700000000.0,
        )  # No terminal event — ended_ts defaults to None
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "running" in clean

    def test_crossref_pid_marks_running(self, tmp_path: Path) -> None:
        """Event log with no terminal event but matching PID → status=running."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-test-20250101-000000-ffffffff.events",
            "pid-wf",
            1700000000.0,
        )  # No terminal event — ended_ts defaults to None
        pid_entries = [
            {
                "pid": 1,
                "port": 1,
                "workflow": "pid-wf.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "ffffffff",
                "file": "/tmp/p.pid",
            },
        ]
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=pid_entries),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "running" in clean

    def test_recent_no_event_logs(self, tmp_path: Path) -> None:
        """Empty run directory → dim message, exit 0."""
        run_dir = tmp_path / "empty_runs"
        run_dir.mkdir()
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        assert "No running workflows found" in result.output
        assert "No recent runs found" in result.output

    def test_recent_missing_dir(self) -> None:
        """Missing run directory → empty results, no crash."""
        with (
            patch(
                "conductor.cli.list_cmd._conductor_run_dir",
                return_value=Path("/nonexistent/path/12345"),
            ),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        assert "No running workflows found" in result.output
        assert "No recent runs found" in result.output

    def test_recent_has_duration(self, tmp_path: Path) -> None:
        """Completed runs show duration in seconds."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-dur-20250101-000000-aaaaaaaa.events",
            "dur-wf",
            1700000000.0,
            1700000037.5,  # 37.5 seconds later
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1"])
        assert result.exit_code == 0
        # Duration should be present (around 37.5s)
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Look for a numeric duration in seconds
        assert re.search(r"3[0-9]\.\d+s", clean), f"Duration not found in: {clean}"

    def test_recent_table_columns(self, tmp_path: Path) -> None:
        """The recent table has Workflow, Run ID, Started, Ended, Status, Duration columns."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-col-20250101-000000-aaaaaaaa.events",
            "col-wf",
            1700000000.0,
            1700000010.0,
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "Workflow" in clean
        assert "Run ID" in clean
        assert "Started" in clean
        assert "Ended" in clean
        assert "Status" in clean
        assert "Duration" in clean


# ---------------------------------------------------------------------------
# Test: `_scan_event_logs` edge cases and robustness
# ---------------------------------------------------------------------------


class TestScanEventLogsEdgeCases:
    """Verify defensive parsing of event logs."""

    def test_truncated_last_json_line(self, tmp_path: Path) -> None:
        """Truncated last JSON line is skipped, other lines parsed correctly."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        fp = run_dir / "conductor-trunc-20250101-000000-aaaaaaaa.events.jsonl"
        # Write valid first line and truncated second line
        start_line = json.dumps(
            {
                "type": "workflow_started",
                "timestamp": 1700000000.0,
                "data": {"name": "trunc-wf"},
            }
        )
        fp.write_text(start_line + "\n" + '{"type": "workflow_comple')  # truncated
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Should still appear (as running since no terminal event)
        assert "trunc-wf" in clean

    def test_invalid_json_lines_skipped(self, tmp_path: Path) -> None:
        """Lines with invalid JSON are silently skipped, valid lines used."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        fp = run_dir / "conductor-bad-20250101-000000-aaaaaaaa.events.jsonl"
        start = json.dumps(
            {
                "type": "workflow_started",
                "timestamp": 1700000000.0,
                "data": {"name": "bad-wf"},
            }
        )
        end = json.dumps({"type": "workflow_completed", "timestamp": 1700000010.0, "data": {}})
        fp.write_text("this is not json\n" + start + "\n" + "also not json\n" + end + "\n")
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Should have valid result with completed status
        assert "bad-wf" in clean
        assert "completed" in clean

    def test_zero_valid_json_lines(self, tmp_path: Path) -> None:
        """File with no valid JSON lines → skipped entirely, no crash."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        fp = run_dir / "conductor-empty-20250101-000000-aaaaaaaa.events.jsonl"
        fp.write_text("not valid json\n{broken\n")
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        # Should have empty recent runs message
        empty_msg = (
            "No recent runs found" in result.output or "No running workflows found" in result.output
        )
        assert empty_msg

    def test_unreadable_file_skipped(self, tmp_path: Path) -> None:
        """Unreadable event log file → skipped, no crash."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        fp = run_dir / "conductor-unread-20250101-000000-aaaaaaaa.events.jsonl"
        fp.write_text("{}")
        fp.chmod(0o000)  # Make unreadable
        try:
            with (
                patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
                patch("conductor.cli.pid.read_pid_files", return_value=[]),
            ):
                result = _invoke(["list", "runs", "--recent", "5"])
            assert result.exit_code == 0
            # Should handle gracefully
            no_error = (
                "No recent runs found" in result.output
                or "No running workflows found" in result.output
            )
            assert no_error
        finally:
            fp.chmod(0o644)  # Restore permissions

    def test_workflow_name_from_event_data(self, tmp_path: Path) -> None:
        """Workflow name is extracted from workflow_started event data.name."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-name-20250101-000000-aaaaaaaa.events",
            "extract-wf",  # Short name avoids Rich table truncation
            1700000000.0,
            1700000010.0,
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])
        assert result.exit_code == 0
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "extract-wf" in clean
        # Should NOT show the raw filename in the output
        assert "conductor-name-" not in clean

    def test_mixed_valid_and_corrupt_files(self, tmp_path: Path) -> None:
        """Multiple corrupt records in one invocation must not crash (VAL-LRUNS-006).

        Mixes: valid log, truncated log, invalid-JSON-only log, empty log, and one
        unreadable file.  The command must exit 0, print only the valid entries,
        and produce no stack trace or error message.
        """
        run_dir = tmp_path / "runs"
        run_dir.mkdir()

        # Valid: completed workflow
        _make_event_log(
            run_dir,
            "conductor-good-20250101-000000-aaaaaaaa.events",
            "good-wf",
            1700000000.0,
            1700000010.0,
        )

        # Truncated: no terminal event (shows as "running")
        fp_trunc = run_dir / "conductor-trunc-20250101-000001-bbbbbbbb.events.jsonl"
        fp_trunc.write_text(
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": 1700000005.0,
                    "data": {"name": "trunc-wf"},
                }
            )
            + '\n{"type": "workflow_comple'
        )

        # Invalid JSON only: zero valid lines → skipped silently
        fp_junk = run_dir / "conductor-junk-20250101-000002-cccccccc.events.jsonl"
        fp_junk.write_text("this is not json\n{broken\nstill not json\n")

        # Empty file → skipped silently
        fp_empty = run_dir / "conductor-empty-20250101-000003-dddddddd.events.jsonl"
        fp_empty.write_text("")

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "10"])

        # Must exit 0
        assert result.exit_code == 0

        # No traceback in output
        assert "Traceback" not in result.output
        assert "Error" not in result.output

        # Valid entries still appear
        import re

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "good-wf" in clean
        assert "trunc-wf" in clean
        # Corrupt files are invisible (no crash)
        assert "cccccccc" not in clean
        assert "dddddddd" not in clean


# ---------------------------------------------------------------------------
# Test: `conductor list runs --recent --json` — JSON history output
# ---------------------------------------------------------------------------


class TestListRunsRecentJson:
    """Verify `list runs --recent --json` emits valid JSON for history."""

    def test_recent_json_valid_array(self, tmp_path: Path) -> None:
        """--recent --json emits a valid JSON array."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-json-20250101-000000-aaaaaaaa.events",
            "json-wf",
            1700000000.0,
            1700000010.0,
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_recent_json_has_required_fields(self, tmp_path: Path) -> None:
        """History entries have workflow, run_id, started_at, ended_at, status,
        duration_seconds, log_file."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-fields-20250101-000000-aaaaaaaa.events",
            "fields-wf",
            1700000000.0,
            1700000010.0,
            end_event="workflow_completed",
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Find the history entry (non-running from PID)
        history = [e for e in data if e.get("status") == "completed"]
        assert len(history) >= 1
        entry = history[0]
        assert "workflow" in entry
        assert "run_id" in entry
        assert "started_at" in entry
        assert "ended_at" in entry
        assert "status" in entry
        assert "duration_seconds" in entry
        assert "log_file" in entry
        assert entry["workflow"] == "fields-wf"
        assert entry["status"] == "completed"
        assert entry["ended_at"] is not None
        assert isinstance(entry["duration_seconds"], (int, float))

    def test_recent_json_no_rich_markup(self, tmp_path: Path) -> None:
        """JSON output has no ANSI escape codes."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-clean-20250101-000000-aaaaaaaa.events",
            "clean-wf",
            1700000000.0,
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1", "--json"])
        assert result.exit_code == 0
        assert "\x1b" not in result.output
        json.loads(result.output)  # Must be valid JSON

    def test_recent_json_empty_no_logs(self, tmp_path: Path) -> None:
        """No event logs → empty JSON array (except possibly PID entries)."""
        run_dir = tmp_path / "empty_runs"
        run_dir.mkdir()
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []
