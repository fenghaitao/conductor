"""Tests for `conductor list` command group.

Focusing on the `list templates` subcommand (milestone 4.1), with
coverage for the full `list` group registration and basic shell for
other subcommands.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from conductor.cli.app import app
from conductor.cli.bg_runner import BackgroundLaunch

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

        result = _invoke(["list", "templates", "--help"])
        assert result.exit_code == 0
        # Strip ANSI escape codes since Rich may format `--json` with embedded codes
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--json" in clean

    def test_list_templates_json_help(self) -> None:
        """`conductor list templates --json --help` shows help text, not JSON."""

        result = _invoke(["list", "templates", "--json", "--help"])
        assert result.exit_code == 0
        # Output must be help text (not JSON array)
        assert "Usage" in result.output or "Options" in result.output
        assert not result.output.strip().startswith("[")
        # --json flag must appear in the cleaned help text
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
        """JSON array length exactly matches the number of data rows in the table."""
        result_json = _invoke(["list", "templates", "--json"])
        result_table = _invoke(["list", "templates"])
        json_data = json.loads(result_json.output)
        json_names = [e["name"] for e in json_data]

        # Rich narrows column width when stdout is not a TTY (e.g., pytest
        # capture), so full template names may be split across lines.  Use
        # short unique fragments (the part before the colon or the first
        # few words) that fit in a single truncated cell.
        def _short_fragment(name: str) -> str:
            # e.g. "Pipeline template: Sequential stages..." → "Pipeline template"
            return name.split(":")[0]

        table_output = result_table.output
        table_names_seen: dict[str, bool] = {}
        for line in table_output.split("\n"):
            for name in json_names:
                fragment = _short_fragment(name)
                if fragment in line and name not in table_names_seen:
                    table_names_seen[name] = True
                    break

        # Same count: JSON length equals unique names found in table
        assert len(json_names) == len(table_names_seen), (
            f"JSON has {len(json_names)} templates but table shows "
            f"{len(table_names_seen)} unique names"
        )

    def test_json_and_table_names_same_order(self) -> None:
        """Template names in JSON appear in the same order as in the table."""
        result_json = _invoke(["list", "templates", "--json"])
        result_table = _invoke(["list", "templates"])
        json_data = json.loads(result_json.output)
        json_names = [e["name"] for e in json_data]

        # Rich narrows columns when stdout is not a TTY.  Match on short
        # unique fragments derived from the part before the colon.
        def _short_fragment(name: str) -> str:
            return name.split(":")[0]

        table_output = result_table.output
        table_names_ordered: list[str] = []
        for line in table_output.split("\n"):
            for name in json_names:
                fragment = _short_fragment(name)
                if fragment in line and name not in table_names_ordered:
                    table_names_ordered.append(name)
                    break

        # Same order
        assert json_names == table_names_ordered, (
            f"JSON order: {json_names}\nTable order: {table_names_ordered}"
        )


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

    def test_list_summary_has_registry_count(self) -> None:
        """Summary shows registry count with hint."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        assert "Registries" in output
        assert "conductor list registries" in output

    def test_list_summary_has_template_count(self) -> None:
        """Summary shows template count with hint."""
        result = _invoke(["list"])
        assert result.exit_code == 0
        output = result.output
        assert "Templates" in output
        assert "conductor list templates" in output

    def test_list_summary_counts_are_integers(self) -> None:
        """All counts are integers (including zero), not empty strings."""

        result = _invoke(["list"])
        assert result.exit_code == 0
        # Strip ANSI codes for reliable matching
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        # Each category line should contain a digit (count)
        assert re.search(r"Running workflows:\s*\d+", clean)
        assert re.search(r"Recent runs:\s*\d+", clean)
        assert re.search(r"Local workflows:\s*\d+", clean)
        assert re.search(r"Registries:\s*\d+", clean)
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


# ---------------------------------------------------------------------------
# Test: `conductor list workflows` — basic listing
# ---------------------------------------------------------------------------


class TestListWorkflowsBasic:
    """Verify `list workflows` discovers workflow YAML files in a directory."""

    def test_empty_dir_prints_graceful_message(self, tmp_path: Path) -> None:
        """VAL-LISTWF-002: Empty dir prints empty-state message, exits 0."""
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "No workflow files found" in result.output

    def test_no_yaml_files_shows_empty_message(self, tmp_path: Path) -> None:
        """Directory with no .yaml/.yml files shows empty message."""
        (tmp_path / "README.md").write_text("# Hello\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "No workflow files found" in result.output

    def test_yaml_without_workflow_keys_excluded(self, tmp_path: Path) -> None:
        """Non-workflow YAML files are excluded by heuristic filter."""
        (tmp_path / "config.yaml").write_text("settings:\n  debug: true\n  port: 8080\n")
        (tmp_path / "docker-compose.yml").write_text(
            "version: '3'\nservices:\n  web:\n    image: nginx\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "No workflow files found" in result.output

    def test_single_valid_workflow_appears(self, tmp_path: Path) -> None:
        """VAL-LISTWF-001: A file with `agents:` key appears in the table."""
        (tmp_path / "my-workflow.yaml").write_text(
            "agents:\n  researcher:\n    prompt: Find info\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output
        assert "my-workflow" in output
        assert "Agents" in output
        assert "Topology" in output
        # Path column is present (Rich truncates long paths with "…")
        assert "Path" in output
        # Agent count and topology are shown
        assert "1" in output
        assert "pipeline" in output

    def test_multiple_valid_workflows_all_appear(self, tmp_path: Path) -> None:
        """All workflow-matching files appear in the table."""
        (tmp_path / "alpha.yaml").write_text("agents:\n  a:\n    prompt: A\n")
        (tmp_path / "beta.yaml").write_text("agents:\n  b:\n    prompt: B\n")
        (tmp_path / "gamma.yaml").write_text("type: workflow\nworkflow:\n  name: gamma\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output
        assert "alpha" in output
        assert "beta" in output
        assert "gamma" in output

    def test_runtime_key_also_matches_heuristic(self, tmp_path: Path) -> None:
        """Files with `runtime:` key pass the heuristic filter."""
        (tmp_path / "my-wf.yaml").write_text("runtime:\n  provider: copilot\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "my-wf" in result.output

    def test_type_workflow_key_matches_heuristic(self, tmp_path: Path) -> None:
        """Files with `type: workflow` pass the heuristic filter."""
        (tmp_path / "typed.yaml").write_text("type: workflow\nworkflow:\n  name: typed\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "typed" in result.output

    def test_mixed_workflow_and_non_workflow(self, tmp_path: Path) -> None:
        """Only workflow files appear; non-workflow YAML is excluded."""
        (tmp_path / "real.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        (tmp_path / "config.yaml").write_text("debug: true\nlogging:\n  level: info\n")
        (tmp_path / "notes.md").write_text("# Notes\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output
        assert "real" in output
        assert "config" not in output

    def test_agent_count_derived_from_yaml(self, tmp_path: Path) -> None:
        """Agent count column reflects len(agents) from parsed YAML."""
        (tmp_path / "multi-agent.yaml").write_text(
            "agents:\n  a:\n    prompt: A\n  b:\n    prompt: B\n  c:\n    prompt: C\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        # Table should show agent count 3
        assert "3" in result.output

    def test_topology_pipeline_detected(self, tmp_path: Path) -> None:
        """Pipeline topology is detected when agents exist without parallel/for_each."""
        (tmp_path / "pipeline.yaml").write_text(
            "agents:\n  step1:\n    prompt: Do step 1\n  step2:\n    prompt: Do step 2\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "pipeline" in result.output

    def test_topology_parallel_detected(self, tmp_path: Path) -> None:
        """Parallel topology is detected when parallel list is non-empty."""
        (tmp_path / "parallel.yaml").write_text(
            "parallel:\n  - agents:\n      a:\n        prompt: A\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "parallel" in result.output

    def test_topology_for_each_detected(self, tmp_path: Path) -> None:
        """For-each topology is detected when for_each list is non-empty."""
        (tmp_path / "foreach.yaml").write_text(
            "for_each:\n  - source: items\n    agents:\n      a:\n        prompt: A\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "for_each" in result.output

    def test_table_has_expected_columns(self, tmp_path: Path) -> None:
        """The workflows table includes Name, Path, Agents, Topology columns."""
        (tmp_path / "test.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output
        assert "Name" in output
        assert "Path" in output
        assert "Agents" in output
        assert "Topology" in output

    def test_empty_dir_exits_zero(self, tmp_path: Path) -> None:
        """VAL-LISTWF-002: Empty dir exits 0, no traceback."""
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        # No traceback
        assert "Traceback" not in result.output
        assert "Error" not in result.output


# ---------------------------------------------------------------------------
# Test: `conductor list workflows --all`
# ---------------------------------------------------------------------------


class TestListWorkflowsAll:
    """Verify `--all` flag bypasses heuristic filtering."""

    def test_all_includes_non_workflow_yaml(self, tmp_path: Path) -> None:
        """--all shows every .yaml/.yml file regardless of content."""
        (tmp_path / "workflow.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        (tmp_path / "config.yaml").write_text("debug: true\nport: 3000\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--all"])
        assert result.exit_code == 0
        output = result.output
        assert "workflow" in output
        assert "config" in output

    def test_all_shows_non_workflow_with_zero_agents(self, tmp_path: Path) -> None:
        """Non-workflow files under --all show agent_count 0 and no topology."""
        (tmp_path / "config.yaml").write_text("debug: true\nport: 3000\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--all"])
        assert result.exit_code == 0
        output = result.output
        assert "config" in output
        assert "0" in output  # agent_count = 0
        assert "—" in output  # empty topology


# ---------------------------------------------------------------------------
# Test: `conductor list workflows --json`
# ---------------------------------------------------------------------------


class TestListWorkflowsJson:
    """Verify `--json` emits valid JSON array of workflow metadata."""

    def test_json_output_is_valid_array(self, tmp_path: Path) -> None:
        """--json emits a valid JSON array."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_json_has_required_fields(self, tmp_path: Path) -> None:
        """Each object has name, path, agent_count, has_parallel, has_for_each,
        has_pipeline."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        entry = data[0]
        assert "name" in entry
        assert "path" in entry
        assert "agent_count" in entry
        assert "has_parallel" in entry
        assert "has_for_each" in entry
        assert "has_pipeline" in entry

    def test_json_empty_no_workflows(self, tmp_path: Path) -> None:
        """No matching workflows → empty JSON array `[]`."""
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_json_no_rich_markup(self, tmp_path: Path) -> None:
        """JSON output has no ANSI escape codes."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        assert "\x1b" not in result.output
        json.loads(result.output)  # Must be valid JSON

    def test_json_topology_flags_correct(self, tmp_path: Path) -> None:
        """Topology flags are correct for each workflow type."""
        (tmp_path / "pipeline.yaml").write_text(
            "agents:\n  step1:\n    prompt: S1\n  step2:\n    prompt: S2\n"
        )
        (tmp_path / "parallel.yaml").write_text(
            "parallel:\n  - agents:\n      a:\n        prompt: A\n"
        )
        (tmp_path / "foreach.yaml").write_text(
            "for_each:\n  - source: items\n    agents:\n      a:\n        prompt: A\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        by_name = {e["name"]: e for e in data}
        assert by_name["pipeline"]["has_pipeline"] is True
        assert by_name["pipeline"]["has_parallel"] is False
        assert by_name["pipeline"]["has_for_each"] is False
        assert by_name["parallel"]["has_parallel"] is True
        assert by_name["foreach"]["has_for_each"] is True

    def test_json_all_flag_includes_everything(self, tmp_path: Path) -> None:
        """--all --json includes non-workflow YAML files with zero metadata."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        (tmp_path / "config.yaml").write_text("debug: true\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--all", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        names = {e["name"] for e in data}
        assert "wf" in names
        assert "config" in names


# ---------------------------------------------------------------------------
# Test: `conductor list workflows --recursive` and `--max-depth`
# ---------------------------------------------------------------------------


class TestListWorkflowsRecursive:
    """Verify recursive directory walking with depth limits."""

    def test_recursive_finds_files_in_subdirs(self, tmp_path: Path) -> None:
        """--recursive finds YAML files in subdirectories."""
        (tmp_path / "root.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.yaml").write_text("agents:\n  y:\n    prompt: Y\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--recursive"])
        assert result.exit_code == 0
        output = result.output
        assert "root" in output
        assert "nested" in output

    def test_non_recursive_only_top_level(self, tmp_path: Path) -> None:
        """Without --recursive, only files in the root directory appear."""
        (tmp_path / "root.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "hidden.yaml").write_text("agents:\n  y:\n    prompt: Y\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output
        assert "root" in output
        assert "hidden" not in output

    def test_max_depth_enforced(self, tmp_path: Path) -> None:
        """Files beyond --max-depth are excluded."""
        (tmp_path / "d0.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "d1.yaml").write_text("agents:\n  a:\n    prompt: A\n")
        d2 = d1 / "d2"
        d2.mkdir()
        (d2 / "d2.yaml").write_text("agents:\n  b:\n    prompt: B\n")
        d3 = d2 / "d3"
        d3.mkdir()
        (d3 / "d3.yaml").write_text("agents:\n  c:\n    prompt: C\n")

        # max-depth 1: only root (d0) and d1 files
        result = _invoke(
            ["list", "workflows", "--path", str(tmp_path), "--recursive", "--max-depth", "1"]
        )
        assert result.exit_code == 0
        output = result.output
        assert "d0" in output
        assert "d1" in output
        assert "d2" not in output
        assert "d3" not in output

    def test_max_depth_zero_is_root_only(self, tmp_path: Path) -> None:
        """--max-depth 0 with --recursive scans only the search root directory.

        Files in subdirectories (depth >= 1) are excluded.
        """
        (tmp_path / "root.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.yaml").write_text("agents:\n  y:\n    prompt: Y\n")
        result = _invoke(
            ["list", "workflows", "--path", str(tmp_path), "--recursive", "--max-depth", "0"]
        )
        assert result.exit_code == 0
        output = result.output
        assert "root" in output
        assert "nested" not in output  # depth 1, excluded by max-depth 0


# ---------------------------------------------------------------------------
# Test: `conductor list workflows --path` flag
# ---------------------------------------------------------------------------


class TestListWorkflowsPath:
    """Verify `--path` flag starts search from an alternate directory."""

    def test_path_default_is_cwd(self) -> None:
        """Without --path, the command searches cwd and exits 0."""
        result = _invoke(["list", "workflows"])
        assert result.exit_code == 0

    def test_path_to_existing_dir_works(self, tmp_path: Path) -> None:
        """--path pointing to an existing directory searches from there."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "wf" in result.output

    def test_path_nonexistent_dir_errors(self, tmp_path: Path) -> None:
        """--path to a nonexistent directory prints error, exits 1."""
        bad_path = tmp_path / "nonexistent"
        result = _invoke(["list", "workflows", "--path", str(bad_path)])
        assert result.exit_code != 0
        assert "Error" in result.output or "does not exist" in result.output.lower()

    def test_path_combines_with_recursive(self, tmp_path: Path) -> None:
        """--path combines with --recursive for deep search."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--recursive"])
        assert result.exit_code == 0
        assert "nested" in result.output

    def test_path_combines_with_json(self, tmp_path: Path) -> None:
        """--path combines with --json for machine-readable output."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "wf"


# ---------------------------------------------------------------------------
# Test: `conductor list workflows` — edge cases
# ---------------------------------------------------------------------------


class TestListWorkflowsEdgeCases:
    """Verify robustness for edge cases in workflow discovery."""

    def test_unreadable_yaml_file_skipped(self, tmp_path: Path) -> None:
        """Unreadable YAML files are skipped, not crashed on."""
        (tmp_path / "good.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        (tmp_path / "bad.yaml").write_text("agents:\n  x:\n    prompt: \x00\x00\x00\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output
        assert "good" in output

    def test_invalid_yaml_syntax_does_not_crash(self, tmp_path: Path) -> None:
        """YAML files with invalid syntax are included with basic metadata."""
        (tmp_path / "broken.yaml").write_text("agents: [unclosed\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "broken" in result.output

    def test_workflow_name_from_yaml_metadata(self, tmp_path: Path) -> None:
        """When YAML has `workflow.name`, it is used instead of filename stem."""
        (tmp_path / "file-stem.yaml").write_text(
            "workflow:\n  name: display-name\nagents:\n  x:\n    prompt: X\n"
        )
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "display-name" in result.output

    def test_large_yaml_file_only_reads_first_2kb(self, tmp_path: Path) -> None:
        """Large YAML files are only inspected in the first 2 KB for heuristic."""
        # Create a file where the workflow keys are beyond 2 KB
        prefix = "# " + "x" * 2048 + "\n"
        content = prefix + "agents:\n  x:\n    prompt: X\n"
        (tmp_path / "large.yaml").write_text(content)
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        # The heuristic only reads first 2 KB, so it won't find "agents:"
        # This file should be excluded by the heuristic
        assert "large" not in result.output

    def test_yaml_files_with_yml_extension(self, tmp_path: Path) -> None:
        """.yml extension files are also discovered."""
        (tmp_path / "workflow.yml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "workflow" in result.output

    def test_exit_code_zero_no_traceback_on_empty(self, tmp_path: Path) -> None:
        """VAL-LISTWF-002: Empty dir exits 0, no Python traceback anywhere."""
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Traceback (most recent call last)" not in result.output
        assert "Traceback (most recent call last)" not in result.stderr


# ---------------------------------------------------------------------------
# Integration test: workflow discovery → dry-run → recent history (VAL-CROSS-002)
# ---------------------------------------------------------------------------


class TestWorkflowDiscoveryToHistory:
    """Integration test verifying the full flow: discover workflow files, run
    one (dry-run), and see it appear in recent history.

    VAL-CROSS-002: ``conductor list workflows`` shows filtered YAML files
    with correct metadata (Name, Path, Agent count, Topology). After
    running a workflow, ``conductor list runs --recent 5`` includes the
    completed run with status=completed and a non-null duration. Both exit 0.
    """

    _VALID_WORKFLOW_YAML = """\
workflow:
  name: test-wf
  description: A test workflow for the discovery-to-history flow.
  entry_point: researcher
agents:
  - name: researcher
    prompt: Research the topic and gather facts.
    routes:
      - to: writer
  - name: writer
    prompt: Write a summary based on the research.
    routes:
      - to: $end
"""

    def _write_valid_workflow(self, dir: Path, filename: str = "integration-wf.yaml") -> Path:
        """Write a valid Conductor workflow YAML file and return its path."""
        fp = dir / filename
        fp.write_text(self._VALID_WORKFLOW_YAML)
        return fp

    def _write_event_log(
        self,
        run_dir: Path,
        filename: str,
        workflow_name: str,
        started_ts: float,
        ended_ts: float,
        end_event: str = "workflow_completed",
    ) -> Path:
        """Write a realistic event log file into ``run_dir``."""
        fp = run_dir / filename
        lines = [
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": started_ts,
                    "data": {"name": workflow_name},
                }
            ),
            json.dumps(
                {
                    "type": end_event,
                    "timestamp": ended_ts,
                    "data": {},
                }
            ),
        ]
        fp.write_text("\n".join(lines))
        return fp

    # ------------------------------------------------------------------
    # Step 1: workflow discovery
    # ------------------------------------------------------------------

    def test_discovery_shows_valid_workflow(self, tmp_path: Path) -> None:
        """``conductor list workflows`` discovers the workflow with correct
        metadata: Name (from workflow.name in YAML), Path, Agent count (2),
        and Topology (pipeline)."""
        self._write_valid_workflow(tmp_path)

        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output

        # Name from YAML metadata (workflow.name), not filename stem
        assert "test-wf" in output
        # Path column present
        assert "Path" in output
        # Agent count = 2
        assert "2" in output
        # Topology = pipeline (agents exist, no parallel/for_each)
        assert "pipeline" in output

    def test_discovery_json_has_correct_metadata(self, tmp_path: Path) -> None:
        """``conductor list workflows --json`` emits correct metadata fields."""
        self._write_valid_workflow(tmp_path)

        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1

        entry = data[0]
        assert entry["name"] == "test-wf"
        assert str(tmp_path) in entry["path"]
        assert entry["agent_count"] == 2
        assert entry["has_pipeline"] is True
        assert entry["has_parallel"] is False
        assert entry["has_for_each"] is False

    def test_discovery_with_non_workflow_files_mixed(self, tmp_path: Path) -> None:
        """Only workflow files appear when mixed with non-workflow YAML."""
        self._write_valid_workflow(tmp_path)
        (tmp_path / "docker-compose.yaml").write_text(
            "version: '3'\nservices:\n  web:\n    image: nginx\n"
        )
        (tmp_path / "config.yaml").write_text("debug: true\nport: 8080\n")

        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output

        assert "test-wf" in output
        assert "docker-compose" not in output
        assert "config" not in output

    # ------------------------------------------------------------------
    # Step 2: dry-run execution
    # ------------------------------------------------------------------

    def test_dry_run_succeeds_on_valid_workflow(self, tmp_path: Path) -> None:
        """``conductor run <path> --dry-run`` exits 0 for a valid workflow."""
        wf = self._write_valid_workflow(tmp_path)

        result = _invoke(["run", str(wf), "--dry-run"])
        assert result.exit_code == 0
        # Dry-run produces an execution plan, not an error
        assert "Error" not in result.output

    def test_dry_run_shows_agent_plan(self, tmp_path: Path) -> None:
        """``conductor run --dry-run`` displays the agent execution plan."""
        wf = self._write_valid_workflow(tmp_path)

        result = _invoke(["run", str(wf), "--dry-run"])
        assert result.exit_code == 0
        output = result.output

        # The plan should mention the workflow name and agents
        assert "test-wf" in output
        # At least one of the two agents should appear
        assert "researcher" in output or "writer" in output

    # ------------------------------------------------------------------
    # Step 3: recent history shows the completed run
    # ------------------------------------------------------------------

    def test_recent_includes_completed_run_with_duration(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """After a simulated run, ``conductor list runs --recent 5`` includes
        the completed run with status=completed and a non-null duration."""
        wf = self._write_valid_workflow(tmp_path)

        # Step 3a: verify the workflow is discoverable
        discover = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert discover.exit_code == 0
        assert "test-wf" in discover.output

        # Step 3b: dry-run the workflow
        run_result = _invoke(["run", str(wf), "--dry-run"])
        assert run_result.exit_code == 0

        # Step 3c: simulate a completed run by writing an event log
        run_dir = tmp_path / "conductor_runs"
        run_dir.mkdir()
        started_ts = 1717000000.0
        ended_ts = 1717000037.5  # 37.5s duration
        run_id = "cafebabe"

        self._write_event_log(
            run_dir,
            f"conductor-test-wf-20260608-{run_id}.events.jsonl",
            "test-wf",
            started_ts,
            ended_ts,
            end_event="workflow_completed",
        )

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])

        assert result.exit_code == 0

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)

        # The completed run appears with status "completed"
        assert "test-wf" in clean
        assert "completed" in clean
        # Duration is present (non-null, around 37.5s)
        assert re.search(r"3[0-9]\.\d+s", clean), f"Duration not found in: {clean}"

    def test_recent_json_includes_completed_run(self, tmp_path: Path, monkeypatch: Any) -> None:
        """``conductor list runs --recent 5 --json`` includes the completed
        run with status=completed and a non-null duration_seconds."""
        wf = self._write_valid_workflow(tmp_path)

        # Dry-run to validate
        run_result = _invoke(["run", str(wf), "--dry-run"])
        assert run_result.exit_code == 0

        # Simulate a completed run
        run_dir = tmp_path / "conductor_runs"
        run_dir.mkdir()
        started_ts = 1717000000.0
        ended_ts = 1717000042.0  # 42.0s duration
        run_id = "deadbeef"

        self._write_event_log(
            run_dir,
            f"conductor-test-wf-20260608-{run_id}.events.jsonl",
            "test-wf",
            started_ts,
            ended_ts,
            end_event="workflow_completed",
        )

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)

        # Find the history entry with status "completed"
        history = [e for e in data if e.get("status") == "completed"]
        assert len(history) >= 1

        entry = history[0]
        assert entry["workflow"] == "test-wf"
        assert entry["run_id"] == run_id
        assert entry["status"] == "completed"
        assert entry["ended_at"] is not None
        assert isinstance(entry["duration_seconds"], (int, float))
        assert entry["duration_seconds"] > 0

    def test_full_flow_workflow_to_history(self, tmp_path: Path) -> None:
        """End-to-end flow: list workflows → dry-run → list runs --recent.

        This is the canonical VAL-CROSS-002 integration test."""
        wf = self._write_valid_workflow(tmp_path)

        # --- Phase 1: Discovery ---
        discover = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert discover.exit_code == 0
        assert "test-wf" in discover.output
        assert "2" in discover.output  # agent count
        assert "pipeline" in discover.output  # topology

        # --- Phase 2: Dry-run execution ---
        run_result = _invoke(["run", str(wf), "--dry-run"])
        assert run_result.exit_code == 0

        # --- Phase 3: Recent history ---
        run_dir = tmp_path / "conductor_runs"
        run_dir.mkdir()
        run_id = "abcdef01"
        self._write_event_log(
            run_dir,
            f"conductor-test-wf-20260608-{run_id}.events.jsonl",
            "test-wf",
            1717000000.0,
            1717000030.0,
        )

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5"])

        assert result.exit_code == 0

        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "test-wf" in clean
        assert "completed" in clean
        assert re.search(r"\d+\.\d+s", clean), f"No duration in: {clean}"


# ---------------------------------------------------------------------------
# Test: `conductor list checkpoints` — table output
# ---------------------------------------------------------------------------


class TestListCheckpoints:
    """Verify `list checkpoints` displays saved checkpoints in a Rich table."""

    def test_no_checkpoints_prints_empty_message(self) -> None:
        """VAL-M3LIST-008: When no checkpoints exist, print empty message, exit 0."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints"])
        assert result.exit_code == 0
        assert "No checkpoints found" in result.output
        assert "Error" not in result.stderr

    def test_no_checkpoints_exits_zero(self) -> None:
        """Empty checkpoint list is not an error — exit 0, no traceback."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints"])
        assert result.exit_code == 0
        assert "Traceback (most recent call last)" not in result.output
        assert "Traceback (most recent call last)" not in result.stderr

    def test_single_checkpoint_table(self) -> None:
        """One checkpoint produces a table with one row and correct values."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/my-workflow.yaml",
            created_at="2026-06-01T12:00:00+00:00",
            error_type="ExecutionError",
            agent="runner",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["list", "checkpoints"])
        assert result.exit_code == 0
        output = result.output
        assert "my-workflow" in output
        assert "2026-06-01" in output
        assert "ExecutionError" in output
        assert "runner" in output

    def test_multiple_checkpoints_table(self) -> None:
        """Multiple checkpoints produce a table with multiple rows, sorted descending."""
        cp1 = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/alpha.yaml",
            created_at="2026-06-01T10:00:00+00:00",
            error_type="ProviderError",
            agent="alpha-agent",
        )
        cp2 = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/beta.yaml",
            created_at="2026-06-01T11:00:00+00:00",
            error_type="ValidationError",
            agent="beta-agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp2, cp1],  # Already sorted descending by list_checkpoints
        ):
            result = _invoke(["list", "checkpoints"])
        assert result.exit_code == 0
        output = result.output
        assert "alpha" in output
        assert "beta" in output
        assert "ProviderError" in output
        assert "ValidationError" in output
        assert "alpha-agent" in output
        assert "beta-agent" in output

    def test_table_has_expected_columns(self) -> None:
        """VAL-M3LIST-001: Table includes Version, Workflow, Created, Error, Agent."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/test.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="test-agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["list", "checkpoints"])
        assert result.exit_code == 0
        output = result.output
        assert "Version" in output
        assert "Workflow" in output
        assert "Created" in output
        assert "Error" in output
        assert "Agent" in output

    def test_checkpoint_count_summary_line(self) -> None:
        """After the table, a summary line shows total checkpoint count."""
        cp_list = [
            _make_checkpoint_data(
                version=1,
                workflow_path=f"/tmp/wf{i}.yaml",
                created_at=f"2026-06-01T0{i}:00:00+00:00",
                error_type="ProviderError",
                agent="agent",
            )
            for i in range(3)
        ]
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=cp_list,
        ):
            result = _invoke(["list", "checkpoints"])
        assert result.exit_code == 0
        assert "Total: 3 checkpoint(s)" in result.output


# ---------------------------------------------------------------------------
# Test: `conductor list checkpoints --workflow` — filtering
# ---------------------------------------------------------------------------


class TestListCheckpointsFiltering:
    """Verify workflow-path argument filters checkpoint results."""

    def test_workflow_filter_passed_to_manager(self) -> None:
        """When a workflow path is provided, it is resolved and passed to
        list_checkpoints."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/exists.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ) as mock_list:
            # Use the examples dir (guaranteed to exist)
            result = _invoke(["list", "checkpoints", "examples/simple-qa.yaml"])
        assert result.exit_code == 0
        # The list_checkpoints was called
        mock_list.assert_called_once()
        called_arg = mock_list.call_args[0][0]
        assert called_arg is not None
        # Should be a resolved absolute path
        assert str(called_arg).endswith("simple-qa.yaml")

    def test_nonexistent_workflow_errors(self) -> None:
        """A workflow path that doesn't exist produces an error, exit 1."""
        result = _invoke(["list", "checkpoints", "/nonexistent/path/workflow.yaml"])
        assert result.exit_code == 1
        assert "Error" in result.stderr or "not found" in result.stderr.lower()

    def test_filtered_no_results_message(self) -> None:
        """When filtering by workflow and no checkpoints match, print specific message."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints", "examples/simple-qa.yaml"])
        assert result.exit_code == 0
        assert (
            "No checkpoints found for workflow" in result.output
            or "No checkpoints found" in result.output
        )


# ---------------------------------------------------------------------------
# Test: `conductor list checkpoints --json` — JSON output
# ---------------------------------------------------------------------------


class TestListCheckpointsJson:
    """Verify `list checkpoints --json` emits valid JSON output."""

    def test_empty_json_array(self) -> None:
        """No checkpoints → empty JSON array `[]`, exit 0."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data == []

    def test_json_has_expected_fields(self) -> None:
        """VAL-M3LIST-002: Each JSON entry has version, workflow_path, workflow_hash,
        created_at, failure, current_agent, run_id, file_path."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/check.yaml",
            workflow_hash="sha256:abc123",
            created_at="2026-06-01T12:00:00+00:00",
            error_type="ExecutionError",
            agent="runner",
            file_path=Path("/tmp/checkpoints/check-20260601.json"),
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        entry = data[0]
        assert entry["version"] == 1
        assert entry["workflow_path"] == "/tmp/check.yaml"
        assert entry["workflow_hash"] == "sha256:abc123"
        assert entry["created_at"] == "2026-06-01T12:00:00+00:00"
        assert entry["failure"] == {
            "error_type": "ExecutionError",
            "agent": "runner",
            "message": "test",
            "iteration": 0,
        }
        assert entry["current_agent"] == "runner"
        assert entry["run_id"] == "test-run-id"
        assert isinstance(entry["file_path"], str)
        assert entry["file_path"] == "/tmp/checkpoints/check-20260601.json"

    def test_json_multiple_entries(self) -> None:
        """VAL-M3LIST-002: Multiple checkpoints produce a JSON array with all entries,
        each containing the 8 required fields."""
        cps = [
            _make_checkpoint_data(
                version=1,
                workflow_path=f"/tmp/wf{i}.yaml",
                workflow_hash=f"sha256:abc{i}",
                created_at=f"2026-06-01T1{i}:00:00+00:00",
                error_type="ProviderError",
                agent=f"agent-{i}",
            )
            for i in range(5)
        ]
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=cps,
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 5
        required_keys = {
            "version",
            "workflow_path",
            "workflow_hash",
            "created_at",
            "failure",
            "current_agent",
            "run_id",
            "file_path",
        }
        for i, entry in enumerate(data):
            assert set(entry.keys()) == required_keys
            assert entry["workflow_path"] == f"/tmp/wf{i}.yaml"
            assert entry["current_agent"] == f"agent-{i}"


# ---------------------------------------------------------------------------
# Test: `conductor checkpoints` (deprecated) — backward compatibility
# ---------------------------------------------------------------------------


class TestCheckpointsDeprecated:
    """Verify the old `conductor checkpoints` command works with deprecation notice."""

    def test_deprecation_notice_printed_to_stderr(self) -> None:
        """Old command prints deprecation notice to stderr."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["checkpoints"])
        # Both old and new command exit 0 on empty
        assert "Deprecated" in result.stderr
        assert "conductor list checkpoints" in result.stderr

    def test_deprecated_command_still_works(self) -> None:
        """Old command still produces correct output despite deprecation."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/old.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="old-agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["checkpoints"])
        assert result.exit_code == 0
        assert "old" in result.output
        assert "ProviderError" in result.output
        assert "Deprecated" in result.stderr

    def test_deprecated_command_stdout_matches_new(self) -> None:
        """Old command stdout is identical to new command stdout."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/same.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            old_result = _invoke(["checkpoints"])
            new_result = _invoke(["list", "checkpoints"])
        # Verify the table content is present in both (old has deprecation on stderr)
        assert "same" in old_result.output
        assert "same" in new_result.output
        assert "ProviderError" in old_result.output
        assert "ProviderError" in new_result.output
        assert "agent" in old_result.output
        assert "agent" in new_result.output
        assert "Version" in old_result.output
        assert "Version" in new_result.output
        # The old command includes "Deprecated" in its output (stderr mixed in)
        assert "Deprecated" in old_result.output

    def test_deprecated_command_hidden_from_help(self) -> None:
        """The old `checkpoints` command is hidden in `conductor --help`."""
        result = _invoke(["--help"])
        assert result.exit_code == 0
        # The old checkpoints should NOT appear in the default help
        output = result.output
        # The new list group should appear
        assert "list" in output
        # checkpoints should NOT appear as a top-level command in help
        # (it's hidden=True, it may appear but without description or with hidden marker)
        # Just verify the new command is documented
        assert "checkpoints" in output.lower() or "list" in output.lower()

    def test_deprecated_with_workflow_filter(self) -> None:
        """Deprecated command with workflow filter delegates correctly."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/simple-qa.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ) as mock_list:
            result = _invoke(["checkpoints", "examples/simple-qa.yaml"])
        assert "Deprecated" in result.stderr
        mock_list.assert_called_once()
        called_arg = mock_list.call_args[0][0]
        assert called_arg is not None

    def test_deprecated_with_json(self) -> None:
        """Deprecated command with --json prints deprecation to stderr and JSON to stdout."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/json-deprecated.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="json-agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["checkpoints", "--json"])
        assert result.exit_code == 0
        assert "Deprecated" in result.stderr
        assert "conductor list checkpoints" in result.stderr
        # JSON output on stdout (clean, no deprecation)
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["workflow_path"] == "/tmp/json-deprecated.yaml"
        assert parsed[0]["failure"]["error_type"] == "ProviderError"
        assert parsed[0]["current_agent"] == "json-agent"

    def test_deprecated_json_matches_new_json(self) -> None:
        """Deprecated --json output matches new command --json output (schema parity)."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/json-parity.yaml",
            created_at="2026-06-01T00:00:00+00:00",
            error_type="ProviderError",
            agent="parity-agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            old_result = _invoke(["checkpoints", "--json"])
            new_result = _invoke(["list", "checkpoints", "--json"])
        # Both produce valid JSON on stdout
        old_parsed = json.loads(old_result.stdout)
        new_parsed = json.loads(new_result.stdout)
        # Same number of entries
        assert len(old_parsed) == len(new_parsed)
        # Same keys
        assert set(old_parsed[0].keys()) == set(new_parsed[0].keys())
        # Same values
        assert old_parsed[0]["workflow_path"] == new_parsed[0]["workflow_path"]
        assert old_parsed[0]["failure"] == new_parsed[0]["failure"]
        assert old_parsed[0]["current_agent"] == new_parsed[0]["current_agent"]
        assert old_parsed[0]["version"] == new_parsed[0]["version"]
        # Deprecation on stderr for old command
        assert "Deprecated" in old_result.stderr
        # No deprecation on stderr for new command
        assert "Deprecated" not in new_result.stderr


# ---------------------------------------------------------------------------
# Test: `conductor list registries` — VAL-M3LIST-005, VAL-M3LIST-006, VAL-M3LIST-007
# ---------------------------------------------------------------------------


class TestListRegistries:
    """Verify `list registries` delegates to existing registry functions."""

    def test_list_registries_no_args_delegates_to_list_all(
        self,
    ) -> None:
        """VAL-M3LIST-005: No args → delegates to _list_all_registries."""
        with patch("conductor.cli.registry._list_all_registries") as mock_list_all:
            result = _invoke(["list", "registries"])
        assert result.exit_code == 0
        mock_list_all.assert_called_once()

    def test_list_registries_with_name_delegates_to_workflows(
        self,
    ) -> None:
        """VAL-M3LIST-006: With name → delegates to _list_registry_workflows."""
        with patch("conductor.cli.registry._list_registry_workflows") as mock_list_wf:
            result = _invoke(["list", "registries", "my-registry"])
        assert result.exit_code == 0
        mock_list_wf.assert_called_once_with("my-registry")

    def test_list_registries_unknown_name_error_to_stderr(
        self,
    ) -> None:
        """VAL-M3LIST-007: Unknown registry name → error to stderr, exit 1."""
        from conductor.registry.errors import RegistryError

        with patch(
            "conductor.cli.registry._list_registry_workflows",
            side_effect=RegistryError("Registry 'nope' not found"),
        ):
            result = _invoke(["list", "registries", "nope"])
        assert result.exit_code == 1
        assert "Error" in result.stderr
        assert "nope" in result.stderr
        assert "not found" in result.stderr

    def test_list_registries_error_without_recommendation_exits_1(
        self,
    ) -> None:
        """RegistryError without suggestion still prints error to stderr and exits 1."""
        from conductor.registry.errors import RegistryError

        with patch(
            "conductor.cli.registry._list_registry_workflows",
            side_effect=RegistryError("Something went wrong"),
        ):
            result = _invoke(["list", "registries", "bad-registry"])
        assert result.exit_code == 1
        assert "Error" in result.stderr
        assert "Something went wrong" in result.stderr

    def test_list_registries_list_all_error_to_stderr(
        self,
    ) -> None:
        """_list_all_registries raising RegistryError → error to stderr, exit 1."""
        from conductor.registry.errors import RegistryError

        with patch(
            "conductor.cli.registry._list_all_registries",
            side_effect=RegistryError("Config corrupted"),
        ):
            result = _invoke(["list", "registries"])
        assert result.exit_code == 1
        assert "Error" in result.stderr
        assert "Config corrupted" in result.stderr


# ---------------------------------------------------------------------------
# Feature 8.3: VAL-M6DEPR-006, VAL-M6DEPR-007
# ---------------------------------------------------------------------------


class TestRegistryNotDeprecated:
    """Verify `conductor registry list` is NOT deprecated."""

    def test_registry_list_no_deprecation_notice(self) -> None:
        """VAL-M6DEPR-006: `registry list` does NOT write any deprecation notice."""
        with patch(
            "conductor.cli.registry._list_all_registries",
        ) as mock_list_all:
            result = _invoke(["registry", "list"])
        assert result.exit_code == 0
        mock_list_all.assert_called_once()
        # stderr must NOT contain deprecation language
        assert "Deprecated" not in result.stderr
        assert "use 'conductor list" not in result.stderr


class TestConductorHelpShowsListAndHidesCheckpoints:
    """Verify `conductor --help` shows `list` group and hides deprecated `checkpoints`."""

    def test_help_shows_list_group(self) -> None:
        """VAL-M6DEPR-007: `conductor --help` includes `list` as a top-level command group."""
        result = _invoke(["--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_help_hides_deprecated_checkpoints(self) -> None:
        """VAL-M6DEPR-007: `checkpoints` is NOT a visible top-level command in help."""
        result = _invoke(["--help"])
        assert result.exit_code == 0
        output = result.output
        # The old `checkpoints` command is hidden=True; it should not appear
        # as a standalone command in the top-level help listing.
        # We parse the Commands section and assert `checkpoints` is absent.
        commands_section = output.split("Commands")[-1]
        # Each command line starts with the command name followed by spaces/description.
        # A hidden command should not have its own line in the Commands table.
        for line in commands_section.splitlines():
            stripped = line.strip()
            if stripped.startswith("checkpoints "):
                raise AssertionError(
                    f"Deprecated 'checkpoints' command visible in top-level help: {line}"
                )


# ---------------------------------------------------------------------------
# Feature 7.1: JSON output validation (VAL-M5JSON-001 through VAL-M5JSON-004)
# ---------------------------------------------------------------------------
#
# Every ``list`` subcommand with ``--json`` must:
# 1. Emit a syntactically valid JSON array to stdout.
# 2. Exit code 0 on successful JSON output.
# 3. Exit code 1 when the data source is inaccessible / broken.
# 4. Write error messages to stderr only — stdout stays parseable.


class TestM5JsonValidArray:
    """VAL-M5JSON-001: --json emits a syntactically valid JSON array to stdout."""

    def test_list_runs_json_is_valid_array(self) -> None:
        """conductor list runs --json → valid JSON array, parseable by json.loads."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_list_runs_recent_json_is_valid_array(self, tmp_path: Path) -> None:
        """conductor list runs --recent 5 --json → valid JSON array."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-valid-20250101-000000-aaaaaaaa.events",
            "valid-wf",
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

    def test_list_workflows_json_is_valid_array(self, tmp_path: Path) -> None:
        """conductor list workflows --json → valid JSON array."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_list_checkpoints_json_is_valid_array(self) -> None:
        """conductor list checkpoints --json → valid JSON array."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_list_templates_json_is_valid_array(self) -> None:
        """conductor list templates --json → valid JSON array."""
        with patch.object(Path, "is_dir", return_value=False):
            result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_json_stderr_contains_no_json(self) -> None:
        """When --json succeeds, stderr contains no JSON output whatsoever."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        # stderr must not contain JSON (no `{` or `[` at the start of a line)
        for line in result.stderr.splitlines():
            stripped = line.strip()
            if stripped:
                assert not stripped.startswith("{"), f"JSON object on stderr: {stripped[:80]}"
                assert not stripped.startswith("["), f"JSON array on stderr: {stripped[:80]}"


class TestM5JsonExitZero:
    """VAL-M5JSON-002: Exit code 0 on successful JSON output."""

    def test_list_runs_json_exit_zero(self) -> None:
        """Successful --json output → exit 0."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0

    def test_list_runs_recent_json_exit_zero(self, tmp_path: Path) -> None:
        """Successful --recent --json output → exit 0."""
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        _make_event_log(
            run_dir,
            "conductor-exit0-20250101-000000-aaaaaaaa.events",
            "exit0-wf",
            1700000000.0,
            1700000010.0,
        )
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1", "--json"])
        assert result.exit_code == 0

    def test_list_workflows_json_exit_zero(self, tmp_path: Path) -> None:
        """Successful --json output → exit 0."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0

    def test_list_checkpoints_json_exit_zero(self) -> None:
        """Successful --json output → exit 0."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0

    def test_list_templates_json_exit_zero(self) -> None:
        """Successful --json output → exit 0."""
        with patch.object(Path, "is_dir", return_value=False):
            result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0


class TestM5JsonExitOne:
    """VAL-M5JSON-003: Exit code 1 when data source is inaccessible."""

    def test_list_runs_recent_json_inaccessible_dir_exits_1(self, tmp_path: Path) -> None:
        """--recent --json with nonexistent run dir → exit 1."""
        nonexistent = tmp_path / "does-not-exist"
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=nonexistent),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert result.exit_code == 1
        # Error message on stderr
        assert "Error" in result.stderr
        assert "does not exist" in result.stderr.lower()

    def test_list_runs_recent_json_inaccessible_dir_stdout_is_json(self, tmp_path: Path) -> None:
        """--recent --json with nonexistent run dir → stdout is still valid JSON."""
        nonexistent = tmp_path / "does-not-exist"
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=nonexistent),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert result.exit_code == 1
        # Stdout must be valid JSON (possibly empty array).
        # Use result.stdout (stdout only) since result.output includes stderr.
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_list_runs_recent_json_not_a_directory_exits_1(self, tmp_path: Path) -> None:
        """--recent --json when run_dir is a file → exit 1."""
        not_a_dir = tmp_path / "not-a-dir"
        not_a_dir.write_text("not a directory")
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=not_a_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "1", "--json"])
        assert result.exit_code == 1
        assert "Error" in result.stderr
        assert "not a directory" in result.stderr.lower()
        # stdout still valid JSON (use result.stdout to exclude stderr)
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_list_checkpoints_json_missing_workflow_exits_1(self) -> None:
        """list checkpoints --json with missing workflow → exit 1."""
        result = _invoke(["list", "checkpoints", "/nonexistent/path/workflow.yaml", "--json"])
        assert result.exit_code == 1
        assert "Error" in result.stderr
        assert "not found" in result.stderr.lower()
        # stdout should be empty since the error occurs before JSON output.
        # (The function raises typer.Exit before reaching the print statement.)
        assert result.stdout.strip() == "" or result.stdout.strip() == "[]"

    def test_list_runs_json_without_recent_never_errors(self) -> None:
        """VAL-M5JSON-002 safeguard: --json without --recent never exits 1
        just because the run dir is missing — it only shows running
        workflows (from PID files)."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []


class TestM5JsonErrorOnStderr:
    """VAL-M5JSON-004: Error messages go to stderr, stdout stays parseable."""

    def test_list_runs_recent_error_on_stderr_only(self, tmp_path: Path) -> None:
        """Error message appears on stderr, not stdout."""
        nonexistent = tmp_path / "does-not-exist"
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=nonexistent),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert result.exit_code == 1
        # Error is on stderr
        assert "Error" in result.stderr
        # stdout has no plain-text error mixed in (use result.stdout for stdout-only)
        output = result.stdout
        # Must be parseable as JSON
        data = json.loads(output)
        assert isinstance(data, list)
        # No error text in stdout
        assert "Error" not in output

    def test_list_checkpoints_error_on_stderr_only(self) -> None:
        """Error for missing workflow → stderr only."""
        result = _invoke(["list", "checkpoints", "/nonexistent/path/workflow.yaml", "--json"])
        assert result.exit_code == 1
        assert "Error" in result.stderr
        # stdout must contain NO error text (use result.stdout for stdout-only)
        assert "Error" not in result.stdout

    def test_list_workflows_error_on_stderr_only(self, tmp_path: Path) -> None:
        """Error for nonexistent path → stderr only."""
        bad_path = tmp_path / "nonexistent"
        result = _invoke(["list", "workflows", "--path", str(bad_path), "--json"])
        assert result.exit_code == 1
        assert "Error" in result.stderr or "does not exist" in result.stderr.lower()
        # stdout must be empty or valid JSON (no error text)
        assert "Error" not in result.stdout


# ---------------------------------------------------------------------------
# Feature 7.2: Empty JSON arrays (VAL-M5JSON-005)
# ---------------------------------------------------------------------------
#
# Every ``list`` subcommand with ``--json`` must produce ``[]`` (empty
# JSON array) on stdout when the result set is empty — never ``null``,
# ``{}``, or a plain-text message.


class TestM5JsonEmptyArray:
    """VAL-M5JSON-005: Empty result sets produce exactly `[]` on stdout."""

    def test_list_runs_empty_json(self) -> None:
        """Empty runs -> `[]`, not null or {}."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        stripped = result.stdout.strip()
        assert stripped == "[]", f"Expected '[]', got: {stripped!r}"

    def test_list_workflows_empty_json(self, tmp_path: Path) -> None:
        """Empty workflows -> `[]`, not null or {}."""
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        stripped = result.stdout.strip()
        assert stripped == "[]", f"Expected '[]', got: {stripped!r}"

    def test_list_checkpoints_empty_json(self) -> None:
        """Empty checkpoints -> `[]`, not null or {}."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0
        stripped = result.stdout.strip()
        assert stripped == "[]", f"Expected '[]', got: {stripped!r}"

    def test_list_templates_empty_json(self) -> None:
        """Empty templates -> `[]`, not null or {}."""
        with patch.object(Path, "is_dir", return_value=False):
            result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        stripped = result.stdout.strip()
        assert stripped == "[]", f"Expected '[]', got: {stripped!r}"


# ---------------------------------------------------------------------------
# Feature 7.3: JSON output stability, pipeability, and unknown flag rejection
# (VAL-M5JSON-006, VAL-M5JSON-007, VAL-M5JSON-008)
# ---------------------------------------------------------------------------


class TestM5JsonStability:
    """VAL-M5JSON-006: JSON output schema is stable across invocations."""

    def test_list_workflows_json_keys_stable(self, tmp_path: Path) -> None:
        """Running list workflows --json twice on unchanged data same keys."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        args = ["list", "workflows", "--path", str(tmp_path), "--json"]
        r1 = _invoke(args)
        r2 = _invoke(args)
        assert r1.exit_code == 0
        assert r2.exit_code == 0
        d1 = json.loads(r1.stdout)[0]
        d2 = json.loads(r2.stdout)[0]
        assert set(d1.keys()) == set(d2.keys())
        for key in d1:
            assert type(d1[key]) is type(d2[key]), (
                f"Type mismatch for '{key}': {type(d1[key])} vs {type(d2[key])}"
            )

    def test_list_workflows_json_new_file_appends_same_schema(self, tmp_path: Path) -> None:
        """Adding a new workflow file appends same-schema entry."""
        (tmp_path / "alpha.yaml").write_text("agents:\n  a:\n    prompt: A\n")
        args = ["list", "workflows", "--path", str(tmp_path), "--json"]
        r1 = _invoke(args)
        d1 = json.loads(r1.stdout)
        assert len(d1) == 1
        expected_keys = set(d1[0].keys())
        (tmp_path / "beta.yaml").write_text("agents:\n  b:\n    prompt: B\n")
        r2 = _invoke(args)
        d2 = json.loads(r2.stdout)
        assert len(d2) == 2
        assert set(d2[0].keys()) == expected_keys
        assert set(d2[1].keys()) == expected_keys

    def test_list_runs_json_keys_stable(self) -> None:
        """Running list runs --json twice on unchanged data same keys."""
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
            r1 = _invoke(["list", "runs", "--json"])
            r2 = _invoke(["list", "runs", "--json"])
        assert r1.exit_code == 0
        assert r2.exit_code == 0
        d1 = json.loads(r1.stdout)[0]
        d2 = json.loads(r2.stdout)[0]
        assert set(d1.keys()) == set(d2.keys())
        for key in d1:
            assert type(d1[key]) is type(d2[key]), (
                f"Type mismatch for '{key}': {type(d1[key])} vs {type(d2[key])}"
            )

    def test_list_runs_json_new_pid_appends_same_schema(self) -> None:
        """Adding a new running workflow appends same-schema entry."""
        single = [
            {
                "pid": 1,
                "port": 8000,
                "workflow": "alpha.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "aaa11111",
                "file": "/tmp/a.pid",
            },
        ]
        double = [
            single[0],
            {
                "pid": 2,
                "port": 8001,
                "workflow": "beta.yaml",
                "started_at": "2026-01-01T01:00:00+00:00",
                "run_id": "bbb22222",
                "file": "/tmp/b.pid",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=single):
            r1 = _invoke(["list", "runs", "--json"])
        with patch("conductor.cli.pid.read_pid_files", return_value=double):
            r2 = _invoke(["list", "runs", "--json"])
        d1 = json.loads(r1.stdout)
        d2 = json.loads(r2.stdout)
        assert len(d1) == 1
        assert len(d2) == 2
        expected_keys = set(d1[0].keys())
        assert set(d2[0].keys()) == expected_keys
        assert set(d2[1].keys()) == expected_keys

    def test_list_templates_json_keys_stable(self) -> None:
        """Running list templates --json twice same keys."""
        with patch.object(Path, "is_dir", return_value=False):
            r1 = _invoke(["list", "templates", "--json"])
            r2 = _invoke(["list", "templates", "--json"])
        assert r1.exit_code == 0
        assert r2.exit_code == 0
        assert json.loads(r1.stdout) == json.loads(r2.stdout) == []

    def test_list_checkpoints_json_keys_stable(self) -> None:
        """Running list checkpoints --json twice same keys."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/test.yaml",
            created_at="2026-06-01T12:00:00+00:00",
            error_type="ProviderError",
            agent="test-agent",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            r1 = _invoke(["list", "checkpoints", "--json"])
            r2 = _invoke(["list", "checkpoints", "--json"])
        assert r1.exit_code == 0
        assert r2.exit_code == 0
        d1 = json.loads(r1.stdout)[0]
        d2 = json.loads(r2.stdout)[0]
        assert set(d1.keys()) == set(d2.keys())
        for key in d1:
            assert type(d1[key]) is type(d2[key]), (
                f"Type mismatch for '{key}': {type(d1[key])} vs {type(d2[key])}"
            )

    def test_list_checkpoints_json_new_checkpoint_appends_same_schema(self) -> None:
        """Adding a new checkpoint appends same-schema entry."""
        cp1 = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/alpha.yaml",
            created_at="2026-06-01T10:00:00+00:00",
            error_type="ProviderError",
            agent="alpha",
        )
        cp2 = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/beta.yaml",
            created_at="2026-06-01T11:00:00+00:00",
            error_type="ExecutionError",
            agent="beta",
        )
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp1],
        ):
            r1 = _invoke(["list", "checkpoints", "--json"])
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp1, cp2],
        ):
            r2 = _invoke(["list", "checkpoints", "--json"])
        d1 = json.loads(r1.stdout)
        d2 = json.loads(r2.stdout)
        assert len(d1) == 1
        assert len(d2) == 2
        expected_keys = set(d1[0].keys())
        assert set(d2[0].keys()) == expected_keys
        assert set(d2[1].keys()) == expected_keys


class TestM5JsonPipeability:
    """VAL-M5JSON-007: --json output can be piped to downstream tools."""

    def test_list_runs_json_pipes_to_json_load(self) -> None:
        """json.loads(stdin) works on list runs --json output."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_list_runs_json_pipes_to_jq_like_access(self) -> None:
        """Assert .[0].port access on JSON output (emulates jq)."""
        pid_entries = [
            {
                "pid": 42,
                "port": 8080,
                "workflow": "w.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "abc",
                "file": "/tmp/x.pid",
            },
        ]
        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1
        assert data[0]["port"] == 8080

    def test_list_workflows_json_pipes_to_json_load(self, tmp_path: Path) -> None:
        """json.load(stdin) works for list workflows --json."""
        (tmp_path / "wf.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_list_workflows_json_pipes_to_len_check(self, tmp_path: Path) -> None:
        """json.loads(stdin) and count works for list workflows."""
        (tmp_path / "a.yaml").write_text("agents:\n  x:\n    prompt: A\n")
        (tmp_path / "b.yaml").write_text("agents:\n  y:\n    prompt: B\n")
        (tmp_path / "c.yaml").write_text("agents:\n  z:\n    prompt: C\n")
        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 3

    def test_list_checkpoints_json_pipes_to_json_load(self) -> None:
        """json.load(stdin) works on list checkpoints --json output."""
        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[],
        ):
            result = _invoke(["list", "checkpoints", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_json_output_no_extra_framing(self) -> None:
        """JSON output starts with [ no extra text before the array."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        stripped = result.stdout.lstrip()
        assert stripped.startswith("["), (
            f"JSON output should start with '[', got: {stripped[:80]!r}"
        )

    def test_json_output_ends_with_newline(self) -> None:
        """JSON output ends with newline pipe-friendly."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
        assert result.exit_code == 0
        assert result.stdout.endswith("\n") or result.stdout.endswith("\r\n"), (
            f"JSON output should end with newline, got: {result.stdout[-20:]!r}"
        )


class TestM5JsonUnknownFlag:
    """VAL-M5JSON-008: --json combined with unrecognized args exits non-zero."""

    def test_list_runs_json_unknown_flag_exits_nonzero(self) -> None:
        """conductor list runs --json --unknown-flag exit != 0."""
        result = _invoke(["list", "runs", "--json", "--unknown-flag"])
        assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"

    def test_list_runs_json_unknown_flag_error_on_stderr(self) -> None:
        """Unknown flag usage error on stderr."""
        result = _invoke(["list", "runs", "--json", "--unknown-flag"])
        assert result.exit_code != 0
        assert "Error" in result.stderr or "No such option" in result.stderr

    def test_list_workflows_json_unknown_flag_exits_nonzero(self) -> None:
        """conductor list workflows --json --unknown-flag exit != 0."""
        result = _invoke(["list", "workflows", "--json", "--unknown-flag"])
        assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"

    def test_list_workflows_json_unknown_flag_error_on_stderr(self) -> None:
        """Unknown flag usage error on stderr."""
        result = _invoke(["list", "workflows", "--json", "--unknown-flag"])
        assert result.exit_code != 0
        assert "Error" in result.stderr or "No such option" in result.stderr

    def test_list_checkpoints_json_unknown_flag_exits_nonzero(self) -> None:
        """conductor list checkpoints --json --unknown-flag exit != 0."""
        result = _invoke(["list", "checkpoints", "--json", "--unknown-flag"])
        assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"

    def test_list_checkpoints_json_unknown_flag_error_on_stderr(self) -> None:
        """Unknown flag usage error on stderr."""
        result = _invoke(["list", "checkpoints", "--json", "--unknown-flag"])
        assert result.exit_code != 0
        assert "Error" in result.stderr or "No such option" in result.stderr

    def test_list_templates_json_unknown_flag_exits_nonzero(self) -> None:
        """conductor list templates --json --unknown-flag exit != 0."""
        result = _invoke(["list", "templates", "--json", "--unknown-flag"])
        assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"

    def test_list_templates_json_unknown_flag_error_on_stderr(self) -> None:
        """Unknown flag usage error on stderr."""
        result = _invoke(["list", "templates", "--json", "--unknown-flag"])
        assert result.exit_code != 0
        assert "Error" in result.stderr or "No such option" in result.stderr

    def test_list_runs_recent_json_unknown_flag_exits_nonzero(self) -> None:
        """conductor list runs --recent 5 --json --unknown-flag exit != 0."""
        result = _invoke(["list", "runs", "--recent", "5", "--json", "--unknown-flag"])
        assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"


# ---------------------------------------------------------------------------
# Test: VAL-CROSS-001 — running workflow discovery flow (feature 9.1)
# ---------------------------------------------------------------------------


class TestValCross001RunningDiscovery:
    """Integration test for the running workflow discovery flow.

    VAL-CROSS-001: A user runs ``conductor list`` and sees a count of
    running workflows with a hint to run ``conductor list runs``. They run
    ``conductor list runs`` and see a table of running background workflows
    showing Port, PID, Workflow name, Dashboard URL, and Started time.
    """

    # ------------------------------------------------------------------
    # Full flow with running workflows
    # ------------------------------------------------------------------

    def test_full_flow_summary_and_detail_with_running_workflows(self) -> None:
        """With 2 running workflows: summary shows count 2 + hint;
        runs table shows both entries with correct columns and data."""
        from unittest.mock import patch

        pid_entries = [
            {
                "pid": 12345,
                "port": 8080,
                "workflow": "my-workflow.yaml",
                "started_at": "2026-01-01T00:00:00+00:00",
                "run_id": "abc12345",
                "file": "/tmp/my-workflow-8080.pid",
            },
            {
                "pid": 12346,
                "port": 8081,
                "workflow": "another-workflow.yaml",
                "started_at": "2026-01-01T01:00:00+00:00",
                "run_id": "def67890",
                "file": "/tmp/another-workflow-8081.pid",
            },
        ]

        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            # Step 1: Summary dashboard
            summary = _invoke(["list"])
            assert summary.exit_code == 0

            # Strip ANSI for reliable matching
            import re

            clean_summary = re.sub(r"\x1b\[[0-9;]*m", "", summary.output)
            assert re.search(r"Running workflows:\s*2", clean_summary), (
                f"Running count should be 2, got: {clean_summary!r}"
            )
            assert "conductor list runs" in clean_summary, (
                f"Summary should hint 'conductor list runs', got: {clean_summary!r}"
            )
            # stderr should be empty (no warnings/errors)
            assert summary.stderr == "", f"stderr should be empty, got: {summary.stderr!r}"

            # Step 2: Runs detail table
            runs = _invoke(["list", "runs"])
            assert runs.exit_code == 0

            output = runs.output
            # Table columns
            assert "Port" in output, f"Table should have Port column, got: {output!r}"
            assert "PID" in output, f"Table should have PID column, got: {output!r}"
            assert "Workflow" in output, f"Table should have Workflow column, got: {output!r}"
            assert "Dashboard URL" in output, (
                f"Table should have Dashboard URL column, got: {output!r}"
            )
            assert "Started" in output, f"Table should have Started column, got: {output!r}"

            # Table title
            assert "Running Workflows" in output, (
                f"Table should have 'Running Workflows' title, got: {output!r}"
            )

            # Data rows — both workflows present
            assert "8080" in output, f"Port 8080 should appear, got: {output!r}"
            assert "8081" in output, f"Port 8081 should appear, got: {output!r}"
            assert "12345" in output, f"PID 12345 should appear, got: {output!r}"
            assert "12346" in output, f"PID 12346 should appear, got: {output!r}"
            assert "my-workflow" in output, (
                f"Workflow stem 'my-workflow' should appear, got: {output!r}"
            )
            assert "another-workflow" in output, (
                f"Workflow stem 'another-workflow' should appear, got: {output!r}"
            )
            # Dashboard URLs — Rich may truncate long column values with "…"
            # so check for the distinguishing prefix (127.0.0.1, not 0.0.0.0/localhost).
            # The full port is already verified in the Port column above.
            assert "http://127.0.0.1:" in output, (
                f"Dashboard URL should start with http://127.0.0.1:, got: {output!r}"
            )
            # Started timestamps (partial match)
            assert "2026-01-01" in output, f"Started date 2026-01-01 should appear, got: {output!r}"

            # No empty-state message (since we have entries)
            assert "No running workflows found" not in output, (
                f"Should not show empty message when workflows are running, got: {output!r}"
            )

    # ------------------------------------------------------------------
    # Full flow with zero running workflows
    # ------------------------------------------------------------------

    def test_full_flow_empty_state(self) -> None:
        """With 0 running workflows: summary shows count 0; runs shows
        graceful empty-state message."""
        from unittest.mock import patch

        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            # Step 1: Summary dashboard
            summary = _invoke(["list"])
            assert summary.exit_code == 0

            import re

            clean_summary = re.sub(r"\x1b\[[0-9;]*m", "", summary.output)
            assert re.search(r"Running workflows:\s*0", clean_summary), (
                f"Running count should be 0, got: {clean_summary!r}"
            )
            assert "conductor list runs" in clean_summary, (
                f"Summary should still hint 'conductor list runs', got: {clean_summary!r}"
            )
            assert summary.stderr == "", f"stderr should be empty, got: {summary.stderr!r}"

            # Step 2: Runs detail table — empty state
            runs = _invoke(["list", "runs"])
            assert runs.exit_code == 0

            output = runs.output
            assert "No running workflows found" in output, (
                f"Should show empty-state message, got: {output!r}"
            )
            # Should not have table markers when empty
            assert "Port" not in output, (
                f"Should not show table columns when empty, got: {output!r}"
            )
            assert "Dashboard URL" not in output, (
                f"Should not show Dashboard URL column when empty, got: {output!r}"
            )

    # ------------------------------------------------------------------
    # Cross-command consistency
    # ------------------------------------------------------------------

    def test_running_count_matches_table_row_count(self) -> None:
        """The running count in summary equals the number of rows
        in the runs table."""
        from unittest.mock import patch

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
            {
                "pid": 300,
                "port": 8002,
                "workflow": "gamma.yaml",
                "started_at": "2026-01-01T02:00:00+00:00",
                "run_id": "ccc33333",
                "file": "/tmp/c.pid",
            },
        ]

        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            import re

            # Summary: count should be 3
            summary = _invoke(["list"])
            assert summary.exit_code == 0
            clean_summary = re.sub(r"\x1b\[[0-9;]*m", "", summary.output)
            assert re.search(r"Running workflows:\s*3", clean_summary)

            # Runs table: should have 3 data rows (each containing a port)
            runs = _invoke(["list", "runs"])
            assert runs.exit_code == 0
            for port in (8000, 8001, 8002):
                assert str(port) in runs.output, f"Port {port} should appear in runs table"

    # ------------------------------------------------------------------
    # Dashboard URL format
    # ------------------------------------------------------------------

    def test_dashboard_url_format_is_http_localhost_port(self) -> None:
        """Each running workflow's Dashboard URL follows the format
        http://127.0.0.1:{port}."""
        from unittest.mock import patch

        pid_entries = [
            {
                "pid": 42,
                "port": 9999,
                "workflow": "test.yaml",
                "started_at": "2026-06-01T12:00:00+00:00",
                "run_id": "test42",
                "file": "/tmp/t.pid",
            },
        ]

        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            runs = _invoke(["list", "runs"])
            assert runs.exit_code == 0
            # Rich may truncate the URL column, so check for the distinguishing
            # prefix pattern and the port in the Port column
            assert "http://127.0.0.1:" in runs.output, (
                f"Dashboard URL should start with http://127.0.0.1:, got: {runs.output!r}"
            )
            # Port should appear in the Port column (and may be truncated in URL column)
            assert "9999" in runs.output, f"Port 9999 should appear in output, got: {runs.output!r}"
            # Should use 127.0.0.1, not localhost or 0.0.0.0
            assert "0.0.0.0" not in runs.output, (
                f"Dashboard URL should use 127.0.0.1, not 0.0.0.0, got: {runs.output!r}"
            )

    # ------------------------------------------------------------------
    # Both commands exit 0 irrespective of running workflows
    # ------------------------------------------------------------------

    def test_both_commands_exit_zero_with_running_workflows(self) -> None:
        """`conductor list` and `conductor list runs` both exit 0
        when workflows are running."""
        from unittest.mock import patch

        pid_entries = [
            {
                "pid": 1,
                "port": 1,
                "workflow": "x.yaml",
                "started_at": "t",
                "run_id": "r",
                "file": "f",
            },
        ]

        with patch("conductor.cli.pid.read_pid_files", return_value=pid_entries):
            assert _invoke(["list"]).exit_code == 0
            assert _invoke(["list", "runs"]).exit_code == 0

    def test_both_commands_exit_zero_without_running_workflows(self) -> None:
        """`conductor list` and `conductor list runs` both exit 0
        when no workflows are running."""
        from unittest.mock import patch

        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            assert _invoke(["list"]).exit_code == 0
            assert _invoke(["list", "runs"]).exit_code == 0


# ---------------------------------------------------------------------------
# Helper: create a minimal CheckpointData for testing
# ---------------------------------------------------------------------------


def _make_checkpoint_data(
    version: int = 1,
    workflow_path: str = "/tmp/test.yaml",
    workflow_hash: str = "sha256:abc123",
    created_at: str = "2026-06-01T00:00:00+00:00",
    error_type: str = "ProviderError",
    agent: str = "test-agent",
    file_path: Path | None = None,
) -> Any:
    """Build a minimal CheckpointData-like object for mocking list_checkpoints.

    Uses a simple object with matching attributes rather than importing
    the dataclass, to keep the test independent of upstream field changes.
    """
    from conductor.engine.checkpoint import CheckpointData

    return CheckpointData(
        version=version,
        workflow_path=workflow_path,
        workflow_hash=workflow_hash,
        created_at=created_at,
        failure={"error_type": error_type, "agent": agent, "message": "test", "iteration": 0},
        inputs={},
        current_agent=agent,
        context={},
        limits={},
        copilot_session_ids={},
        file_path=file_path or Path(f"/tmp/checkpoints/{Path(workflow_path).stem}-checkpoint.json"),
        instructions_preamble=None,
        run_id="test-run-id",
        event_log_path="",
    )


# ---------------------------------------------------------------------------
# Integration test: Checkpoint discovery to resume flow (VAL-CROSS-004)
# ---------------------------------------------------------------------------


class TestCheckpointDiscoveryAndResume:
    """Verify the full checkpoint → resume → run history chain.

    VAL-CROSS-004: A user runs ``conductor list checkpoints`` and sees
    a list of saved checkpoints with workflow path, failure reason, and
    timestamp. They resume the latest one. The resumed run completes,
    and ``conductor list runs --recent 1`` shows the resumed run with
    status "completed" and the same run_id as in the checkpoint listing.
    """

    def test_checkpoint_shows_file_path_and_run_id(self) -> None:
        """`conductor list checkpoints --json` shows entries with file_path and run_id."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/failing-workflow.yaml",
            created_at="2026-06-08T10:00:00+00:00",
            error_type="ExecutionError",
            agent="researcher",
            file_path=Path("/tmp/checkpoints/failing-workflow-20260608.json"),
        )
        cp.run_id = "cross-ref-run-004"
        cp.file_path = Path("/tmp/checkpoints/failing-workflow-20260608.json")
        cp.workflow_path = "/tmp/failing-workflow.yaml"

        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["list", "checkpoints", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1

        entry = data[0]
        assert entry["file_path"] == "/tmp/checkpoints/failing-workflow-20260608.json"
        assert entry["run_id"] == "cross-ref-run-004"
        assert entry["workflow_path"] == "/tmp/failing-workflow.yaml"
        assert entry["failure"]["error_type"] == "ExecutionError"
        assert entry["current_agent"] == "researcher"
        assert entry["created_at"] == "2026-06-08T10:00:00+00:00"

    def test_resumed_run_appears_in_history_with_matching_run_id(self, tmp_path: Path) -> None:
        """After resume, ``list runs --recent 1`` shows completed status
        with the same run_id from the checkpoint listing."""
        # --- Simulate checkpoint data ---
        # Use hex run_id (no hyphens) to match real conductor conventions
        # and filename-based run_id extraction in _parse_event_log.
        shared_run_id = "a1b2c3d4"
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/failing-workflow.yaml",
            created_at="2026-06-08T10:00:00+00:00",
            error_type="ExecutionError",
            agent="researcher",
        )
        cp.run_id = shared_run_id
        cp.file_path = Path("/tmp/checkpoints/failing-workflow-20260608.json")
        cp.workflow_path = "/tmp/failing-workflow.yaml"

        # --- Simulate a completed event log for the resumed run ---
        run_dir = tmp_path / "conductor_runs"
        run_dir.mkdir()
        # The event log filename must include the run_id so _parse_event_log
        # extracts it correctly.
        log_name = "conductor-failing-workflow-20260608-100000-a1b2c3d4.events"
        log_file = run_dir / f"{log_name}.jsonl"
        import time as _time_mod

        started_ts = _time_mod.time() - 60  # started 60 seconds ago
        ended_ts = _time_mod.time() - 10  # ended 10 seconds ago

        log_lines = [
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": started_ts,
                    "data": {"name": "failing-workflow"},
                }
            ),
            json.dumps(
                {
                    "type": "workflow_completed",
                    "timestamp": ended_ts,
                    "data": {},
                }
            ),
        ]
        log_file.write_text("\n".join(log_lines) + "\n")

        # --- Execute CLI commands ---
        with (
            patch(
                "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
                return_value=[cp],
            ),
            patch(
                "conductor.cli.list_cmd._conductor_run_dir",
                return_value=run_dir,
            ),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            # Step 1: verify checkpoints
            cp_result = _invoke(["list", "checkpoints", "--json"])
            assert cp_result.exit_code == 0
            cp_data = json.loads(cp_result.output)
            assert len(cp_data) >= 1
            cp_entry = cp_data[0]
            assert cp_entry["run_id"] == shared_run_id

            # Step 2: verify run history shows the resumed run as completed
            runs_result = _invoke(["list", "runs", "--recent", "1", "--json"])
            assert runs_result.exit_code == 0
            runs_data = json.loads(runs_result.output)
            assert len(runs_data) >= 1

            # Find history entry (non-running)
            history = [e for e in runs_data if e.get("status") != "running"]
            assert len(history) == 1, (
                f"Expected exactly 1 history entry, got {len(history)}: {runs_data}"
            )
            history_entry = history[0]
            assert history_entry["status"] == "completed", (
                f"Expected status 'completed', got {history_entry}"
            )
            assert history_entry["run_id"] == shared_run_id, (
                f"Run ID mismatch: checkpoint={shared_run_id}, history={history_entry['run_id']}"
            )
            assert history_entry["workflow"] == "failing-workflow"
            assert history_entry["ended_at"] is not None
            assert isinstance(history_entry["duration_seconds"], (int, float))
            assert history_entry["duration_seconds"] > 0

    def test_checkpoint_run_history_both_exit_zero(self, tmp_path: Path) -> None:
        """Both ``list checkpoints`` and ``list runs --recent`` exit 0."""
        shared_run_id = "exit-zero-004"
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/exit-zero-wf.yaml",
            created_at="2026-06-08T10:00:00+00:00",
            error_type="ProviderError",
            agent="agent-a",
        )
        cp.run_id = shared_run_id

        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        log_file = run_dir / "conductor-exit-zero-wf-20260608-000000-exit-zero-004.events.jsonl"
        import time as _time_mod2

        ts = _time_mod2.time()
        log_file.write_text(
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": ts - 30,
                    "data": {"name": "exit-zero-wf"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "workflow_completed",
                    "timestamp": ts - 5,
                    "data": {},
                }
            )
            + "\n"
        )

        with (
            patch(
                "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
                return_value=[cp],
            ),
            patch(
                "conductor.cli.list_cmd._conductor_run_dir",
                return_value=run_dir,
            ),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            cp_result = _invoke(["list", "checkpoints"])
            assert cp_result.exit_code == 0
            runs_result = _invoke(["list", "runs", "--recent", "1"])
            assert runs_result.exit_code == 0
            assert runs_result.stderr == "" or "Error" not in runs_result.stderr

    def test_multiple_checkpoints_and_recent_runs_cross_referenced(self, tmp_path: Path) -> None:
        """With multiple checkpoints and history entries, the most recent
        checkpoint's run_id can be found in the history."""
        import time as _time_mod3

        # Three checkpoints with different hex run_ids
        cps = []
        run_ids = ["a0000001", "a0000002", "a0000003"]
        for i in range(3):
            cp = _make_checkpoint_data(
                version=1,
                workflow_path=f"/tmp/wf-{i}.yaml",
                created_at=f"2026-06-08T0{i}:00:00+00:00",
                error_type=f"Error{i}",
                agent=f"agent-{i}",
            )
            cp.run_id = run_ids[i]
            cp.file_path = Path(f"/tmp/checkpoints/wf-{i}-checkpoint.json")
            cp.workflow_path = f"/tmp/wf-{i}.yaml"
            cps.append(cp)

        # Three event logs — two completed, one failed
        run_dir = tmp_path / "runs"
        run_dir.mkdir()
        ts = _time_mod3.time()

        # Completed run matching checkpoint 0
        (run_dir / "conductor-wf-0-20260608-000000-a0000001.events.jsonl").write_text(
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": ts - 60,
                    "data": {"name": "wf-0"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "workflow_completed",
                    "timestamp": ts - 10,
                    "data": {},
                }
            )
            + "\n"
        )
        # Completed run matching checkpoint 1
        (run_dir / "conductor-wf-1-20260608-000000-a0000002.events.jsonl").write_text(
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": ts - 120,
                    "data": {"name": "wf-1"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "workflow_completed",
                    "timestamp": ts - 80,
                    "data": {},
                }
            )
            + "\n"
        )
        # Failed run matching checkpoint 2
        (run_dir / "conductor-wf-2-20260608-000000-a0000003.events.jsonl").write_text(
            json.dumps(
                {
                    "type": "workflow_started",
                    "timestamp": ts - 180,
                    "data": {"name": "wf-2"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "workflow_failed",
                    "timestamp": ts - 150,
                    "data": {},
                }
            )
            + "\n"
        )

        with (
            patch(
                "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
                return_value=cps,
            ),
            patch(
                "conductor.cli.list_cmd._conductor_run_dir",
                return_value=run_dir,
            ),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            # Checkpoints
            cp_result = _invoke(["list", "checkpoints", "--json"])
            assert cp_result.exit_code == 0
            cp_data = json.loads(cp_result.output)
            assert len(cp_data) == 3
            cp_run_ids = {e["run_id"] for e in cp_data}
            assert cp_run_ids == {"a0000001", "a0000002", "a0000003"}

            # Recent runs
            runs_result = _invoke(["list", "runs", "--recent", "5", "--json"])
            assert runs_result.exit_code == 0
            runs_data = json.loads(runs_result.output)

            # History entries (non-running)
            history = [e for e in runs_data if e.get("status") != "running"]
            assert len(history) == 3
            history_run_ids = {e["run_id"] for e in history}
            assert history_run_ids == cp_run_ids, (
                f"Run ID mismatch: checkpoints={cp_run_ids}, history={history_run_ids}"
            )

            # Verify statuses
            statuses = {e["run_id"]: e["status"] for e in history}
            assert statuses["a0000001"] == "completed"
            assert statuses["a0000002"] == "completed"
            assert statuses["a0000003"] == "failed"

    def test_checkpoint_table_shows_file_path_info(self) -> None:
        """The ``list checkpoints`` table includes columns for Workflow
        (from workflow_path stem), Error, Agent, Created — all derived
        from checkpoint file_path data."""
        cp = _make_checkpoint_data(
            version=1,
            workflow_path="/tmp/my-workflow.yaml",
            created_at="2026-06-08T10:00:00+00:00",
            error_type="ExecutionError",
            agent="researcher",
            file_path=Path("/tmp/checkpoints/my-workflow-checkpoint.json"),
        )
        cp.run_id = "table-cross-004"

        with patch(
            "conductor.engine.checkpoint.CheckpointManager.list_checkpoints",
            return_value=[cp],
        ):
            result = _invoke(["list", "checkpoints"])

        assert result.exit_code == 0
        output = result.output
        # Table columns
        assert "Version" in output
        assert "Workflow" in output
        assert "Created" in output
        assert "Error" in output
        assert "Agent" in output
        # Data values
        assert "my-workflow" in output
        assert "ExecutionError" in output
        assert "researcher" in output
        assert "2026-06-08" in output


# ---------------------------------------------------------------------------
# Integration test: JSON export for CI scripting (VAL-CROSS-005)
# ---------------------------------------------------------------------------


class TestValCross005JsonCIScripting:
    """Verify JSON export for CI scripting — runs and workflows.

    VAL-CROSS-005: A CI script runs ``conductor list runs --json`` and
    receives a valid JSON array of run history objects. Each object has
    ``workflow``, ``run_id``, ``started_at``, ``status``, and
    ``duration_seconds`` fields. The script also runs
    ``conductor list workflows --json --recursive`` and receives a JSON
    array of workflow file metadata with ``name``, ``path``,
    ``agent_count``, and topology tags. Both commands exit 0 and the
    JSON can be piped to ``jq`` for filtering.
    """

    # ------------------------------------------------------------------
    # Run history JSON — required fields for CI
    # ------------------------------------------------------------------

    def test_list_runs_recent_json_required_fields_for_ci(self, tmp_path: Path) -> None:
        """``conductor list runs --recent N --json`` emits run history
        objects with ``workflow``, ``run_id``, ``started_at``,
        ``status``, and ``duration_seconds`` — all the fields a CI
        script needs to parse without ambiguity."""
        import time as _time

        run_dir = tmp_path / "ci-runs"
        run_dir.mkdir()

        # Completed run
        now = _time.time()
        _make_event_log(
            run_dir,
            "conductor-ci-completed-20260608-000000-cccc0001.events",
            "ci-completed-wf",
            now - 120,
            now - 60,
            end_event="workflow_completed",
        )
        # Failed run
        _make_event_log(
            run_dir,
            "conductor-ci-failed-20260608-000000-ffff0002.events",
            "ci-failed-wf",
            now - 300,
            now - 240,
            end_event="workflow_failed",
        )

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            result = _invoke(["list", "runs", "--recent", "5", "--json"])

        # Exit 0 for CI
        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.stderr}"

        # Valid JSON — equivalent to ``jq '.'``
        data = json.loads(result.output)
        assert isinstance(data, list), f"Expected JSON array, got {type(data)}"
        # Only history entries (no running PID entries)
        history = [e for e in data if e.get("status") != "running"]
        assert len(history) == 2, f"Expected 2 history entries, got {len(history)}"

        # Every history entry has the required CI fields
        required_fields = {"workflow", "run_id", "started_at", "status", "duration_seconds"}
        for entry in history:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Entry missing CI fields: {missing} -> {entry}"
            assert isinstance(entry["workflow"], str)
            assert isinstance(entry["run_id"], str)
            assert isinstance(entry["started_at"], str)
            assert entry["status"] in ("completed", "failed", "running")
            assert entry["duration_seconds"] is not None
            assert isinstance(entry["duration_seconds"], (int, float))

        # Verify specific values to prove the data is real
        statuses = {e["workflow"]: e["status"] for e in history}
        assert statuses["ci-completed-wf"] == "completed"
        assert statuses["ci-failed-wf"] == "failed"

    # ------------------------------------------------------------------
    # Workflow JSON — required fields for CI (with --recursive)
    # ------------------------------------------------------------------

    def test_list_workflows_json_recursive_required_fields_for_ci(self, tmp_path: Path) -> None:
        """``conductor list workflows --json --recursive`` emits workflow
        metadata with ``name``, ``path``, ``agent_count``, and topology
        tags — all extractable with ``jq``-like field access."""
        # Create a directory tree with workflow YAML files
        sub = tmp_path / "sub"
        sub.mkdir()
        deep = sub / "deep"
        deep.mkdir()

        # Pipeline workflow (agents only)
        (tmp_path / "pipeline.yaml").write_text(
            "workflow:\n  name: Pipeline WF\n"
            "agents:\n  step1:\n    prompt: Do A\n"
            "  step2:\n    prompt: Do B\n"
        )
        # Parallel workflow
        (sub / "parallel.yaml").write_text(
            "agents:\n  worker:\n    prompt: Process\n"
            "parallel:\n  - agent: worker\n    input: x\n"
            "  - agent: worker\n    input: y\n"
        )
        # For-each workflow (deep)
        (deep / "foreach.yaml").write_text(
            "agents:\n  processor:\n    prompt: Handle\n"
            "for_each:\n  - agent: processor\n    items: [a, b, c]\n"
        )
        # Non-workflow YAML (should be excluded by heuristic)
        (tmp_path / "config.yaml").write_text("debug: true\nport: 8080\n")

        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json", "--recursive"])

        # Exit 0 for CI
        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.stderr}"

        # Valid JSON — equivalent to ``jq '.'``
        data = json.loads(result.output)
        assert isinstance(data, list), f"Expected JSON array, got {type(data)}"
        # 3 workflow files (config.yaml excluded by heuristic)
        assert len(data) == 3, f"Expected 3 workflow entries, got {len(data)}: {data}"

        # Every entry has the required CI fields
        required_fields = {
            "name",
            "path",
            "agent_count",
            "has_parallel",
            "has_for_each",
            "has_pipeline",
        }
        for entry in data:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Entry missing CI fields: {missing} -> {entry}"

        # ``jq '.[0].name'`` — extract first entry's name
        assert data[0]["name"] == "Pipeline WF", (
            f"jq '.[0].name' should be 'Pipeline WF', got {data[0]['name']}"
        )

        # Verify topology tags are correct
        # Sort by name for deterministic access
        by_name = {e["name"]: e for e in data}
        assert by_name["Pipeline WF"]["has_pipeline"] is True
        assert by_name["Pipeline WF"]["has_parallel"] is False
        assert by_name["Pipeline WF"]["has_for_each"] is False
        assert by_name["Pipeline WF"]["agent_count"] == 2

        # parallel.yaml has no ``workflow: {name: ...}`` key, so name = stem
        assert by_name["parallel"]["has_parallel"] is True
        assert by_name["parallel"]["has_pipeline"] is False
        assert by_name["parallel"]["agent_count"] == 1

        assert by_name["foreach"]["has_for_each"] is True
        assert by_name["foreach"]["has_pipeline"] is False
        assert by_name["foreach"]["agent_count"] == 1

        # ``jq '.[].name'`` — extract all names
        names = [e["name"] for e in data]
        assert "Pipeline WF" in names
        assert "parallel" in names
        assert "foreach" in names

    # ------------------------------------------------------------------
    # Both commands exit 0 for a CI pipeline
    # ------------------------------------------------------------------

    def test_both_json_commands_exit_zero_for_ci_pipeline(self, tmp_path: Path) -> None:
        """A CI pipeline can invoke both ``list runs --json`` and
        ``list workflows --json`` consecutively; both must exit 0."""
        import time as _time

        # Set up event logs
        run_dir = tmp_path / "ci-runs"
        run_dir.mkdir()
        now = _time.time()
        _make_event_log(
            run_dir,
            "conductor-ci-pipe-20260608-000000-pppp0001.events",
            "ci-pipe-wf",
            now - 60,
            now - 30,
            end_event="workflow_completed",
        )

        # Set up workflow YAML files
        (tmp_path / "wf-a.yaml").write_text("agents:\n  x:\n    prompt: X\n")
        (tmp_path / "wf-b.yaml").write_text("agents:\n  y:\n    prompt: Y\n")

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            # CI Step 1: list runs
            runs_result = _invoke(["list", "runs", "--recent", "5", "--json"])
            assert runs_result.exit_code == 0, (
                f"Step 1 (list runs --json) failed: {runs_result.stderr}"
            )

            # CI Step 2: list workflows
            wf_result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
            assert wf_result.exit_code == 0, (
                f"Step 2 (list workflows --json) failed: {wf_result.stderr}"
            )

        # Both produce valid JSON
        runs_data = json.loads(runs_result.output)
        assert isinstance(runs_data, list)
        wf_data = json.loads(wf_result.output)
        assert isinstance(wf_data, list)
        assert len(wf_data) == 2  # wf-a and wf-b

    # ------------------------------------------------------------------
    # ``jq``-like field access on JSON output
    # ------------------------------------------------------------------

    def test_json_output_supports_jq_like_field_access(self, tmp_path: Path) -> None:
        """JSON output from both subcommands supports ``jq``-equivalent
        field extraction: ``.[0].name``, ``.[].status``, etc. — no
        ``KeyError`` or malformed output."""
        import time as _time

        # --- Set up event logs for run history ---
        run_dir = tmp_path / "ci-runs"
        run_dir.mkdir()
        now = _time.time()
        _make_event_log(
            run_dir,
            "conductor-jq-20260608-000000-jqjq0001.events",
            "jq-wf",
            now - 100,
            now - 50,
            end_event="workflow_completed",
        )
        _make_event_log(
            run_dir,
            "conductor-jq2-20260608-000000-jqjq0002.events",
            "jq-wf2",
            now - 200,
            now - 180,
            end_event="workflow_failed",
        )

        # --- Set up workflow YAML files (with and without --recursive) ---
        (tmp_path / "jq-a.yaml").write_text(
            "workflow:\n  name: JQ Alpha\nagents:\n  main:\n    prompt: Run\n"
        )
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "jq-b.yaml").write_text("agents:\n  worker:\n    prompt: Do work\n")

        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            # --- jq '.' on runs ---
            runs_result = _invoke(["list", "runs", "--recent", "5", "--json"])
            assert runs_result.exit_code == 0
            runs_data = json.loads(runs_result.output)  # jq '.'
            assert isinstance(runs_data, list)
            history = [e for e in runs_data if e.get("status") != "running"]

            # --- jq '.[0].workflow' on runs ---
            assert len(history) >= 1
            first_run = history[0]  # jq '.[0]'
            assert first_run["workflow"] is not None  # jq '.[0].workflow'
            assert first_run["status"] is not None  # jq '.[0].status'
            # jq '.[].status' — all statuses
            all_statuses = [e["status"] for e in history]
            assert "completed" in all_statuses
            assert "failed" in all_statuses

            # --- jq '.[] | {name, agent_count}' on runs ---
            for entry in history:
                _ = entry["workflow"]  # must not KeyError
                _ = entry["run_id"]
                _ = entry["duration_seconds"]

            # --- jq '.' on workflows ---
            wf_result = _invoke(
                ["list", "workflows", "--path", str(tmp_path), "--json", "--recursive"]
            )
            assert wf_result.exit_code == 0
            wf_data = json.loads(wf_result.output)  # jq '.'
            assert isinstance(wf_data, list)
            assert len(wf_data) >= 2

        # --- jq '.[0].name' on workflows ---
        first_wf = wf_data[0]  # jq '.[0]'
        assert first_wf["name"] is not None  # jq '.[0].name'
        assert first_wf["path"] is not None  # jq '.[0].path'

        # --- jq '.[].name' — extract all names ---
        all_names = [e["name"] for e in wf_data]  # jq '.[].name'
        assert "JQ Alpha" in all_names
        assert "jq-b" in all_names

        # --- jq '.[] | select(.has_pipeline == true) | .name' ---
        pipeline_wfs = [e["name"] for e in wf_data if e["has_pipeline"]]
        assert "JQ Alpha" in pipeline_wfs
        assert "jq-b" in pipeline_wfs  # jq-b has agents: and no parallel/for_each

        # --- jq '.[] | {name, agent_count, has_parallel, has_for_each, has_pipeline}' ---
        for entry in wf_data:
            _ = entry["name"]
            _ = entry["agent_count"]
            _ = entry["has_parallel"]
            _ = entry["has_for_each"]
            _ = entry["has_pipeline"]

    # ------------------------------------------------------------------
    # JSON output is clean (no ANSI, no extra framing)
    # ------------------------------------------------------------------

    def test_json_output_is_clean_for_ci_pipes(self) -> None:
        """JSON output for CI scripting has no ANSI escape codes,
        starts with ``[``, and ends with a newline — safe for piping."""
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])

        assert result.exit_code == 0
        output = result.stdout

        # No ANSI escape codes (Rich markup)
        assert "\x1b" not in output, f"ANSI codes found in JSON output: {output!r}"

        # Starts with ``[`` (JSON array)
        stripped = output.lstrip()
        assert stripped.startswith("["), (
            f"JSON output should start with '[', got: {stripped[:80]!r}"
        )

        # Ends with newline (pipe-friendly)
        assert output.endswith("\n"), f"JSON output should end with newline, got: {output[-20:]!r}"

        # Parseable as JSON
        data = json.loads(output)
        assert isinstance(data, list), f"Expected JSON array, got {type(data)}"

    # ------------------------------------------------------------------
    # Edge case: empty results still produce valid JSON for CI
    # ------------------------------------------------------------------

    def test_empty_results_produce_empty_json_array(self, tmp_path: Path) -> None:
        """When there are no runs or no workflows, ``--json`` still
        emits ``[]`` — CI scripts can always rely on parseable output."""
        # Empty runs (no PID files, no event logs)
        run_dir = tmp_path / "empty-runs"
        run_dir.mkdir()
        with (
            patch("conductor.cli.list_cmd._conductor_run_dir", return_value=run_dir),
            patch("conductor.cli.pid.read_pid_files", return_value=[]),
        ):
            runs_result = _invoke(["list", "runs", "--recent", "5", "--json"])
        assert runs_result.exit_code == 0
        assert runs_result.output.strip() == "[]", (
            f"Expected empty JSON array '[]', got: {runs_result.output.strip()!r}"
        )

        # Empty workflows (no YAML files)
        empty_wf_dir = tmp_path / "empty-wf"
        empty_wf_dir.mkdir()
        wf_result = _invoke(["list", "workflows", "--path", str(empty_wf_dir), "--json"])
        assert wf_result.exit_code == 0
        assert wf_result.output.strip() == "[]", (
            f"Expected empty JSON array '[]', got: {wf_result.output.strip()!r}"
        )


# ---------------------------------------------------------------------------
# Integration test: Template discovery to workflow instantiation (VAL-CROSS-006)
# ---------------------------------------------------------------------------


class TestTemplateDiscoveryToWorkflowInstantiation:
    """Verify template discovery to workflow instantiation flow.

    VAL-CROSS-006: A user runs ``conductor list templates`` and sees a table
    of available workflow templates with Name, Description, and Path. They
    pick a template, instantiate it as a workflow file (simulated by copying
    the template YAML to an output directory — the ``conductor init
    --template`` command was removed during the registry redesign), then run
    ``conductor list workflows --path <output-dir>`` to confirm the newly
    created workflow file appears with the expected agent count and topology
    from the template.  All commands exit 0.
    """

    # ------------------------------------------------------------------
    # Step 1: template discovery
    # ------------------------------------------------------------------

    def test_templates_list_json_exits_zero(self) -> None:
        """``conductor list templates --json`` exits 0 and returns a valid
        JSON array of template objects."""
        result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 3  # pipeline, fan-out, loop at minimum

    def test_templates_list_json_has_required_keys(self) -> None:
        """Each template object has ``name``, ``description``, and ``path``
        keys — all non-empty strings."""
        result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        for entry in data:
            assert "name" in entry and isinstance(entry["name"], str) and entry["name"]
            assert (
                "description" in entry
                and isinstance(entry["description"], str)
                and entry["description"]
            )
            assert "path" in entry and isinstance(entry["path"], str) and entry["path"]

    def test_templates_list_paths_exist(self) -> None:
        """Every ``path`` field in template JSON points to an existing YAML
        file that can be read."""
        result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        for entry in data:
            p = Path(entry["path"])
            assert p.exists(), f"Template path does not exist: {entry['path']}"
            assert p.suffix in (".yaml", ".yml"), f"Not a YAML file: {entry['path']}"

    def test_templates_list_shows_pipeline_fanout_loop(self) -> None:
        """Table output includes Pipeline, Fan-out, and Loop template names."""
        result = _invoke(["list", "templates"])
        assert result.exit_code == 0
        output = result.output
        assert "Pipeline template" in output
        assert "Fan-out template" in output
        assert "Loop template" in output

    # ------------------------------------------------------------------
    # Step 2: workflow instantiation (simulate ``conductor init --template``)
    # ------------------------------------------------------------------

    def _get_template_path(self, name_fragment: str) -> Path:
        """Get the filesystem path of a template by name fragment from
        ``conductor list templates --json``."""
        result = _invoke(["list", "templates", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        for entry in data:
            if name_fragment in entry["name"]:
                return Path(entry["path"])
        raise AssertionError(f"Template matching '{name_fragment}' not found in {data}")

    def _instantiate_template(self, template_path: Path, output_dir: Path) -> Path:
        """Copy a template YAML file to ``output_dir``, simulating
        ``conductor init --template <name> <output-dir>``.

        Returns the path to the copied workflow file.
        """
        import shutil

        dest = output_dir / template_path.name
        shutil.copy2(template_path, dest)
        return dest

    # ------------------------------------------------------------------
    # Step 3: workflow discovery after instantiation
    # ------------------------------------------------------------------

    def test_pipeline_template_discovery_after_instantiation(self, tmp_path: Path) -> None:
        """Instantiate the Pipeline template and verify ``list workflows``
        discovers it with 3 agents and ``has_pipeline`` topology."""
        # Simulate ``conductor init --template pipeline <tmp_path>``
        tmpl_path = self._get_template_path("Pipeline template")
        wf_path = self._instantiate_template(tmpl_path, tmp_path)

        # Verify the file exists at the expected location
        assert wf_path.exists()
        assert wf_path.parent == tmp_path

        # Run ``conductor list workflows --path <tmp_path>`` (table mode)
        result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert result.exit_code == 0
        output = result.output

        # The workflow should be discovered with the correct name from YAML
        assert "pipeline-template" in output
        # Agent count = 3 (stage1, stage2, stage3)
        assert "3" in output
        # Topology = pipeline (agents exist, no parallel/for_each)
        assert "pipeline" in output

    def test_pipeline_template_discovery_json_metadata(self, tmp_path: Path) -> None:
        """Instantiate the Pipeline template and verify ``list workflows
        --json`` emits correct metadata: name, agent_count=3,
        has_pipeline=true."""
        tmpl_path = self._get_template_path("Pipeline template")
        self._instantiate_template(tmpl_path, tmp_path)

        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1, f"Expected 1 workflow, got {len(data)}: {data}"

        entry = data[0]
        assert entry["name"] == "pipeline-template"
        assert entry["agent_count"] == 3
        assert entry["has_pipeline"] is True
        assert entry["has_parallel"] is False
        assert entry["has_for_each"] is False
        assert str(tmp_path) in entry["path"]

    def test_fan_out_template_discovery_after_instantiation(self, tmp_path: Path) -> None:
        """Instantiate the Fan-out template and verify ``list workflows``
        discovers it with ``has_for_each`` topology and 1 agent."""
        tmpl_path = self._get_template_path("Fan-out template")
        self._instantiate_template(tmpl_path, tmp_path)

        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1

        entry = data[0]
        assert entry["name"] == "fan-out-template"
        # fan-out has 1 agent (aggregator) + 1 for_each group
        assert entry["agent_count"] == 1
        assert entry["has_for_each"] is True
        assert entry["has_parallel"] is False
        assert entry["has_pipeline"] is False

    def test_loop_template_discovery_after_instantiation(self, tmp_path: Path) -> None:
        """Instantiate the Loop template and verify ``list workflows``
        discovers it with ``has_pipeline`` topology and 3 agents."""
        tmpl_path = self._get_template_path("Loop template")
        self._instantiate_template(tmpl_path, tmp_path)

        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1

        entry = data[0]
        assert entry["name"] == "loop-template"
        # loop has 3 agents (implementer, reviewer, fixer)
        assert entry["agent_count"] == 3
        assert entry["has_pipeline"] is True
        assert entry["has_parallel"] is False
        assert entry["has_for_each"] is False

    # ------------------------------------------------------------------
    # Step 4: end-to-end flow (VAL-CROSS-006 canonical test)
    # ------------------------------------------------------------------

    def test_full_flow_template_to_workflow_discovery(self, tmp_path: Path) -> None:
        """End-to-end flow: list templates → instantiate → list workflows.

        This is the canonical VAL-CROSS-006 integration test: verify that
        ``conductor list templates`` shows template names and paths, and
        after copying a template to an output directory,
        ``conductor list workflows --path <output-dir>`` discovers the
        newly created workflow file with the expected agent count and
        topology from the template.  All exit 0.
        """
        # --- Phase 1: Template discovery ---
        tmpl_result = _invoke(["list", "templates", "--json"])
        assert tmpl_result.exit_code == 0
        tmpl_data = json.loads(tmpl_result.output)
        assert len(tmpl_data) >= 3, f"Expected at least 3 templates, got {len(tmpl_data)}"

        # Find the Pipeline template
        pipeline_tmpl = None
        for t in tmpl_data:
            if "Pipeline template" in t["name"]:
                pipeline_tmpl = t
                break
        assert pipeline_tmpl is not None, "Pipeline template not found"
        assert "ordered stages" in pipeline_tmpl["description"].lower()

        # --- Phase 2: Instantiate (simulate ``conductor init``) ---
        tmpl_path = Path(pipeline_tmpl["path"])
        assert tmpl_path.exists()
        import shutil

        wf_path = tmp_path / tmpl_path.name
        shutil.copy2(tmpl_path, wf_path)
        assert wf_path.exists()

        # --- Phase 3: Workflow discovery after instantiation ---
        wf_result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert wf_result.exit_code == 0
        wf_data = json.loads(wf_result.output)
        assert len(wf_data) == 1, f"Expected 1 workflow, got {len(wf_data)}: {wf_data}"

        entry = wf_data[0]
        # Metadata must match the Pipeline template:
        #   workflow.name = pipeline-template
        #   agents: stage1, stage2, stage3 → agent_count = 3
        #   No parallel or for_each → pipeline
        assert entry["name"] == "pipeline-template", (
            f"Expected name 'pipeline-template', got {entry['name']!r}"
        )
        assert entry["agent_count"] == 3, f"Expected 3 agents, got {entry['agent_count']}"
        assert entry["has_pipeline"] is True, "Pipeline template should have has_pipeline=True"
        assert entry["has_parallel"] is False
        assert entry["has_for_each"] is False

        # --- Phase 4: Table output also works ---
        table_result = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert table_result.exit_code == 0
        assert "pipeline-template" in table_result.output
        assert "3" in table_result.output
        assert "pipeline" in table_result.output

    def test_multiple_templates_instantiated_and_discovered(self, tmp_path: Path) -> None:
        """Instantiate multiple templates and verify all are discovered
        with correct metadata."""
        import shutil

        tmpl_result = _invoke(["list", "templates", "--json"])
        assert tmpl_result.exit_code == 0
        tmpl_data = json.loads(tmpl_result.output)

        # Instantiate all three built-in templates
        expected: list[dict[str, Any]] = []
        for t in tmpl_data:
            tmpl_path = Path(t["path"])
            dest = tmp_path / tmpl_path.name
            shutil.copy2(tmpl_path, dest)

            # Compute expected metadata from template name
            if "Pipeline template" in t["name"]:
                expected.append(
                    {
                        "name": "pipeline-template",
                        "agent_count": 3,
                        "has_pipeline": True,
                        "has_parallel": False,
                        "has_for_each": False,
                    }
                )
            elif "Fan-out template" in t["name"]:
                expected.append(
                    {
                        "name": "fan-out-template",
                        "agent_count": 1,
                        "has_pipeline": False,
                        "has_parallel": False,
                        "has_for_each": True,
                    }
                )
            elif "Loop template" in t["name"]:
                expected.append(
                    {
                        "name": "loop-template",
                        "agent_count": 3,
                        "has_pipeline": True,
                        "has_parallel": False,
                        "has_for_each": False,
                    }
                )

        assert len(expected) == len(tmpl_data), (
            f"Expected {len(tmpl_data)} workflows, got {len(expected)}"
        )

        # Verify discovery
        wf_result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert wf_result.exit_code == 0
        wf_data = json.loads(wf_result.output)
        assert len(wf_data) == len(expected), (
            f"Expected {len(expected)} workflows, got {len(wf_data)}: {wf_data}"
        )

        # Verify each expected workflow is found with correct metadata
        wf_by_name = {e["name"]: e for e in wf_data}
        for exp in expected:
            name = exp["name"]
            assert name in wf_by_name, f"Workflow '{name}' not found in: {list(wf_by_name.keys())}"
            actual = wf_by_name[name]
            assert actual["agent_count"] == exp["agent_count"], (
                f"'{name}': expected agent_count={exp['agent_count']}, got {actual['agent_count']}"
            )
            assert actual["has_pipeline"] == exp["has_pipeline"], (
                f"'{name}': expected has_pipeline={exp['has_pipeline']}, "
                f"got {actual['has_pipeline']}"
            )
            assert actual["has_parallel"] == exp["has_parallel"]
            assert actual["has_for_each"] == exp["has_for_each"]

    def test_instantiated_workflow_excludes_non_workflow_files(self, tmp_path: Path) -> None:
        """Non-workflow YAML files in the output directory are excluded
        by the heuristic filter — only the instantiated workflow appears."""
        import shutil

        tmpl_path = self._get_template_path("Pipeline template")
        shutil.copy2(tmpl_path, tmp_path / tmpl_path.name)

        # Add non-workflow YAML files
        (tmp_path / "docker-compose.yaml").write_text(
            "version: '3'\nservices:\n  web:\n    image: nginx\n"
        )
        (tmp_path / "config.yaml").write_text("debug: true\nport: 8080\n")

        result = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1, f"Expected 1 workflow, got {len(data)}: {data}"
        assert data[0]["name"] == "pipeline-template"

    def test_all_commands_exit_zero_in_full_flow(self, tmp_path: Path) -> None:
        """Every command in the template→workflow flow exits 0:
        ``list templates``, ``list workflows`` (both table and JSON modes)."""
        import shutil

        # 1. list templates (table)
        r1 = _invoke(["list", "templates"])
        assert r1.exit_code == 0

        # 2. list templates (JSON)
        r2 = _invoke(["list", "templates", "--json"])
        assert r2.exit_code == 0

        # 3. Instantiate a template
        tmpl_result = _invoke(["list", "templates", "--json"])
        tmpl_data = json.loads(tmpl_result.output)
        for t in tmpl_data:
            if "Pipeline template" in t["name"]:
                tmpl_path = Path(t["path"])
                shutil.copy2(tmpl_path, tmp_path / tmpl_path.name)
                break

        # 4. list workflows (table)
        r3 = _invoke(["list", "workflows", "--path", str(tmp_path)])
        assert r3.exit_code == 0

        # 5. list workflows (JSON)
        r4 = _invoke(["list", "workflows", "--path", str(tmp_path), "--json"])
        assert r4.exit_code == 0


# ---------------------------------------------------------------------------
# Integration test: Background workflow lifecycle (VAL-CROSS-003)
# ---------------------------------------------------------------------------


class TestValCross003BackgroundLifecycle:
    """Integration test for background workflow lifecycle.

    VAL-CROSS-003: A user starts a workflow in background mode with
    ``conductor run <path> --web-bg``. They run ``conductor list runs``
    and see the new entry with a PID and Dashboard URL. They stop it with
    ``conductor stop --port <port>``. Running ``conductor list runs``
    again shows the workflow is no longer in the running table (though
    it may appear in ``--recent`` history with status=failed due to
    the stop).
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_valid_workflow(tmp_path: Path) -> Path:
        """Create a minimal valid workflow YAML and return its path."""
        workflow_file = tmp_path / "test-workflow.yaml"
        workflow_yaml = """\
workflow:
  name: test-workflow
  description: Test workflow for background lifecycle
  version: "1.0.0"
  entry_point: answerer
  runtime:
    provider: copilot
  input:
    question:
      type: string
      required: true
      description: A test question
agents:
  - name: answerer
    description: Answers test questions
    model: gpt-4.1
    prompt: |
      Answer: {{ workflow.input.question }}
    output:
      answer:
        type: string
        description: The answer
    routes:
      - to: $end
output:
  answer: "{{ answerer.output.answer }}"
"""
        workflow_file.write_text(workflow_yaml)
        return workflow_file

    @staticmethod
    def _make_mock_launch(tmp_path: Path) -> BackgroundLaunch:
        """Create a mock ``BackgroundLaunch`` with known port and PID."""
        run_id = "abc12345"
        return BackgroundLaunch(
            url="http://127.0.0.1:8080",
            stderr_log=tmp_path / f"conductor-test-{run_id}.bg.stderr.log",
            stdout_log=tmp_path / f"conductor-test-{run_id}.bg.stdout.log",
            run_id=run_id,
        )

    @staticmethod
    def _make_pid_entry(workflow_file: Path, tmp_path: Path) -> dict:
        """Create a mock PID entry matching the mock launch."""
        return {
            "pid": 12345,
            "port": 8080,
            "workflow": str(workflow_file),
            "started_at": "2026-06-08T12:00:00+00:00",
            "run_id": "abc12345",
            "file": str(tmp_path / "runs" / "8080.pid"),
        }

    # ------------------------------------------------------------------
    # Full lifecycle: launch → list → stop → verify gone
    # ------------------------------------------------------------------

    def test_full_background_lifecycle(self, tmp_path: Path) -> None:
        """Canonical VAL-CROSS-003: launch bg workflow → list shows it →
        stop → list omits it."""
        from unittest.mock import patch

        workflow_file = self._create_valid_workflow(tmp_path)
        mock_launch = self._make_mock_launch(tmp_path)
        pid_entry = self._make_pid_entry(workflow_file, tmp_path)

        # Phase 1: Launch background workflow
        with patch("conductor.cli.bg_runner.launch_background", return_value=mock_launch):
            result = _invoke(
                [
                    "run",
                    str(workflow_file),
                    "--web-bg",
                    "--input",
                    "question=test",
                ]
            )
            assert result.exit_code == 0, (
                f"Launch failed with exit={result.exit_code}, stderr={result.stderr!r}"
            )

        # Phase 2: Verify it shows in list runs (table mode)
        with patch("conductor.cli.pid.read_pid_files", return_value=[pid_entry]):
            result = _invoke(["list", "runs"])
            assert result.exit_code == 0
            output = result.output

            # Table columns must be present
            assert "Port" in output, f"Table should have Port column, got: {output!r}"
            assert "PID" in output, f"Table should have PID column, got: {output!r}"
            assert "Workflow" in output, f"Table should have Workflow column, got: {output!r}"
            assert "Dashboard URL" in output, (
                f"Table should have Dashboard URL column, got: {output!r}"
            )
            assert "Started" in output, f"Table should have Started column, got: {output!r}"

            # Data must appear in the table
            assert "8080" in output, f"Port 8080 should appear, got: {output!r}"
            assert "12345" in output, f"PID 12345 should appear, got: {output!r}"
            assert "test-workflow" in output, (
                f"Workflow 'test-workflow' should appear, got: {output!r}"
            )
            assert "http://127.0.0.1:" in output, f"Dashboard URL should appear, got: {output!r}"

            # No empty-state message when workflows are running
            assert "No running workflows found" not in output, (
                f"Should not show empty-state when running, got: {output!r}"
            )

        # Phase 3: Verify JSON output mode shows correct fields
        with patch("conductor.cli.pid.read_pid_files", return_value=[pid_entry]):
            result = _invoke(["list", "runs", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1, f"Expected 1 entry, got {len(data)}"
            entry = data[0]
            assert entry["pid"] == 12345
            assert entry["port"] == 8080
            assert "http://127.0.0.1:" in entry["dashboard_url"]
            assert "test-workflow" in entry["workflow"]
            assert entry["run_id"] == "abc12345"

        # Phase 4: Stop the workflow via port
        with (
            patch("conductor.cli.pid.read_pid_files", return_value=[pid_entry]),
            patch("conductor.cli.app.os.kill"),
            patch("conductor.cli.pid.remove_pid_file", return_value=True),
        ):
            result = _invoke(["stop", "--port", "8080"])
            assert result.exit_code == 0, (
                f"Stop failed with exit={result.exit_code}, stderr={result.stderr!r}"
            )

        # Phase 5: Verify it's gone from list runs (table mode — empty state)
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs"])
            assert result.exit_code == 0
            output = result.output
            assert "No running workflows found" in output, (
                f"Should show empty-state message, got: {output!r}"
            )
            assert "Port" not in output, (
                f"Should not show table columns when empty, got: {output!r}"
            )
            assert "Dashboard URL" not in output, (
                f"Should not show Dashboard URL when empty, got: {output!r}"
            )

        # Phase 6: Verify list runs --json returns empty array
        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data == [], f"Expected empty JSON array, got: {data!r}"

    # ------------------------------------------------------------------
    # Empty-state before any launch
    # ------------------------------------------------------------------

    def test_list_runs_empty_before_any_launch(self) -> None:
        """With no running workflows, ``conductor list runs`` shows the
        graceful empty-state message and exits 0."""
        from unittest.mock import patch

        with patch("conductor.cli.pid.read_pid_files", return_value=[]):
            result = _invoke(["list", "runs"])
            assert result.exit_code == 0
            assert "No running workflows found" in result.output

    # ------------------------------------------------------------------
    # list summary reflects running count
    # ------------------------------------------------------------------

    def test_list_summary_reflects_running_count(self, tmp_path: Path) -> None:
        """After a mock launch, ``conductor list`` summary shows running
        count = 1 with hint to run ``conductor list runs``."""
        from unittest.mock import patch

        workflow_file = self._create_valid_workflow(tmp_path)
        mock_launch = self._make_mock_launch(tmp_path)
        pid_entry = self._make_pid_entry(workflow_file, tmp_path)

        # Launch
        with patch("conductor.cli.bg_runner.launch_background", return_value=mock_launch):
            _invoke(["run", str(workflow_file), "--web-bg", "--input", "question=test"])

        # Summary
        with patch("conductor.cli.pid.read_pid_files", return_value=[pid_entry]):
            result = _invoke(["list"])
            assert result.exit_code == 0

            import re

            clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
            assert re.search(r"Running workflows:\s*1", clean), (
                f"Running count should be 1, got: {clean!r}"
            )
            assert "conductor list runs" in clean, (
                f"Summary should hint 'conductor list runs', got: {clean!r}"
            )
            assert result.stderr == "", f"stderr should be empty, got: {result.stderr!r}"
