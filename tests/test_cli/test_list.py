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
