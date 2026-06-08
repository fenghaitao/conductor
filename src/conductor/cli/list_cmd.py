"""`conductor list` command group — unified discovery of workflows, runs,
checkpoints, registries, and templates.

All subcommands use Rich tables for default output and support ``--json``
for machine-readable output.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from conductor.engine.checkpoint import CheckpointManager, _conductor_run_dir

logger = logging.getLogger("conductor.list")

list_app = typer.Typer(
    name="list",
    help="Discover workflows, runs, checkpoints, and more.",
    no_args_is_help=False,
)

# Rich console for stdout (primary output) and stderr (errors/notices)
output_console = Console()
console = Console(stderr=True)
error_console = Console(stderr=True)

# Well-known template directories (relative to the conductor package root)
_BUILTIN_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "plugins"
    / "conductor-workflow-creator"
    / "assets"
    / "templates"
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_template_headers(filepath: Path) -> tuple[str, str] | None:
    """Extract template name and description from YAML comment headers.

    Template files start with a comment block:

        # Template Name (descriptive title)
        #
        # Description line (often "Use when: ...")

    Args:
        filepath: Path to a YAML template file.

    Returns:
        A ``(name, description)`` tuple if the file has parsable headers,
        or ``None`` if the file lacks the expected comment format.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.debug("Could not read template file: %s", filepath)
        return None

    lines = text.splitlines()
    comment_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # Remove the leading "# " or "#"
            content = stripped[1:].strip()
            comment_lines.append(content)
        else:
            break  # End of comment block

    if len(comment_lines) < 2:
        return None

    name = comment_lines[0]
    # The description is the first non-empty, non-separator comment
    # after the name (skip empty lines and "#" only lines)
    description = ""
    for cl in comment_lines[1:]:
        if cl:
            description = cl
            break

    if not name or not description:
        return None

    return name, description


def _discover_templates(directories: list[Path]) -> list[dict[str, str]]:
    """Discover template files from one or more directories.

    Only YAML files (``.yaml`` / ``.yml``) with parsable comment headers
    are included. Non-YAML files and YAML files without the expected
    template comment format are silently excluded.

    Args:
        directories: List of directories to scan for template files.

    Returns:
        A list of dicts with ``name``, ``description``, and ``path`` keys,
        sorted by name.
    """
    results: list[dict[str, str]] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for yaml_file in sorted(directory.glob("*.yaml")):
            parsed = _parse_template_headers(yaml_file)
            if parsed is not None:
                name, description = parsed
                results.append(
                    {
                        "name": name,
                        "description": description,
                        "path": str(yaml_file.resolve()),
                    }
                )
        for yml_file in sorted(directory.glob("*.yml")):
            parsed = _parse_template_headers(yml_file)
            if parsed is not None:
                name, description = parsed
                results.append(
                    {
                        "name": name,
                        "description": description,
                        "path": str(yml_file.resolve()),
                    }
                )
    results.sort(key=lambda r: r["name"])
    return results


# ---------------------------------------------------------------------------
# Callback: `conductor list` (summary dashboard)
# ---------------------------------------------------------------------------


@list_app.callback(invoke_without_command=True)
def list_summary(ctx: typer.Context) -> None:
    """Print a summary dashboard showing counts of discoverable resources.

    Each count includes a hint for the full subcommand. Only runs when
    no subcommand is given (``conductor list`` without arguments).
    """
    if ctx.invoked_subcommand is not None:
        return  # A subcommand was given, skip the summary
    # Running workflows
    running_count = 0
    try:
        from conductor.cli.pid import read_pid_files

        running_count = len(read_pid_files())
    except Exception:
        logger.debug("Could not read PID files", exc_info=True)

    # Recent runs (count event log files)
    recent_count = 0
    try:
        run_dir = _conductor_run_dir()
        if run_dir.is_dir():
            recent_count = len(list(run_dir.glob("conductor-*.events.jsonl")))
    except Exception:
        logger.debug("Could not scan event logs", exc_info=True)

    # Local workflow files
    workflow_count = 0
    try:
        cwd = Path.cwd()
        for yf in list(cwd.glob("*.yaml")) + list(cwd.glob("*.yml")):
            try:
                text = yf.read_text(encoding="utf-8")[:2048]
                if "agents:" in text or "type: workflow" in text or "runtime:" in text:
                    workflow_count += 1
            except Exception:
                pass
    except Exception:
        logger.debug("Could not scan for workflow files", exc_info=True)

    # Templates
    template_count = 0
    try:
        template_dirs = _get_template_directories()
        template_count = len(_discover_templates(template_dirs))
    except Exception:
        logger.debug("Could not discover templates", exc_info=True)

    # Configured registries
    registry_count = 0
    try:
        from conductor.registry.config import load_config as load_registry_config

        reg_config = load_registry_config()
        registry_count = len(reg_config.registries)
    except Exception:
        logger.debug("Could not load registry config", exc_info=True)

    # Build summary panel
    lines: list[str] = []
    lines.append(
        f"[bold cyan]Running workflows:[/bold cyan] {running_count} "
        f"[dim](conductor list runs)[/dim]"
    )
    lines.append(
        f"[bold cyan]Recent runs:[/bold cyan] {recent_count} "
        f"[dim](conductor list runs --recent)[/dim]"
    )
    lines.append(
        f"[bold cyan]Local workflows:[/bold cyan] {workflow_count} "
        f"[dim](conductor list workflows)[/dim]"
    )
    lines.append(
        f"[bold cyan]Registries:[/bold cyan] {registry_count} "
        f"[dim](conductor list registries)[/dim]"
    )
    lines.append(
        f"[bold cyan]Templates:[/bold cyan] {template_count} [dim](conductor list templates)[/dim]"
    )

    panel = Panel(
        "\n".join(lines),
        title="Conductor Discovery",
        border_style="cyan",
    )
    output_console.print(panel)


# ---------------------------------------------------------------------------
# `conductor list runs`
# ---------------------------------------------------------------------------


@list_app.command("runs")
def list_runs(
    recent: Annotated[
        int,
        typer.Option(
            "--recent",
            help="Show the last N completed/failed runs from event logs.",
            min=0,
        ),
    ] = 0,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON instead of a table.",
        ),
    ] = False,
) -> None:
    """List running background workflows and recent run history.

    Without ``--recent``, shows only running workflows.
    With ``--recent N``, also shows the last N completed/failed runs
    from event logs.
    """
    # Running workflows table
    running_entries: list[dict[str, Any]] = []
    try:
        from conductor.cli.pid import read_pid_files

        running_entries = read_pid_files()
    except Exception:
        logger.debug("Could not read PID files", exc_info=True)

    # Recent history from event logs
    history_entries: list[dict[str, Any]] = []
    running_run_ids: set[str] = {rid for e in running_entries if (rid := e.get("run_id"))}
    if recent > 0:
        try:
            history_entries = _scan_event_logs(
                recent,
                running_run_ids,
                error_on_inaccessible=json_output,
            )
        except OSError as exc:
            # In --json mode, inaccessible run history is a hard error
            # (exit 1) so scripts don't silently receive empty results
            # when the data source is broken. Stdout still gets valid
            # JSON; the error message goes to stderr.
            if json_output:
                console.print(f"[bold red]Error:[/bold red] {exc}")
                _output_runs_json(running_entries, [])
                raise typer.Exit(code=1) from None
            # In table mode, degrade gracefully as before.
            logger.debug("Could not scan event logs: %s", exc)
        except Exception:
            logger.debug("Could not scan event logs", exc_info=True)

    if json_output:
        _output_runs_json(running_entries, history_entries)
        return

    # Build tables
    if running_entries:
        table = Table(title="Running Workflows", show_lines=False)
        table.add_column("Port", style="cyan")
        table.add_column("PID", style="green")
        table.add_column("Workflow", style="bold")
        table.add_column("Dashboard URL", style="blue")
        table.add_column("Started", style="dim")
        for entry in running_entries:
            port = entry.get("port", "?")
            pid = str(entry.get("pid", "?"))
            workflow = Path(entry.get("workflow", "?")).stem
            url = f"http://127.0.0.1:{port}" if port != "?" else "?"
            started = entry.get("started_at", "?")
            table.add_row(str(port), pid, workflow, url, started)
        output_console.print(table)
    else:
        output_console.print("[dim]No running workflows found.[/dim]")

    if history_entries:
        output_console.print()  # blank line separator
        htable = Table(title=f"Recent Runs (last {recent})", show_lines=False)
        htable.add_column("Workflow", style="bold")
        htable.add_column("Run ID", style="dim")
        htable.add_column("Started", style="green")
        htable.add_column("Ended", style="green")
        htable.add_column("Status", style="yellow")
        htable.add_column("Duration", style="cyan")
        for entry in history_entries:
            status = entry["status"]
            status_style = {
                "completed": "green",
                "failed": "red",
                "running": "yellow",
            }.get(status, "")
            duration = entry.get("duration_seconds")
            duration_str = f"{duration:.1f}s" if duration is not None else "—"
            htable.add_row(
                entry["workflow"],
                entry["run_id"],
                entry["started_at"],
                entry.get("ended_at", "—"),
                f"[{status_style}]{status}[/{status_style}]",
                duration_str,
            )
        output_console.print(htable)
    elif recent > 0 and not history_entries:
        output_console.print("[dim]No recent runs found.[/dim]")


def _scan_event_logs(
    recent: int,
    running_run_ids: set[str],
    error_on_inaccessible: bool = False,
) -> list[dict[str, Any]]:
    """Scan JSONL event log files and derive run history entries.

    Args:
        recent: Maximum number of entries to return.
        running_run_ids: Set of run IDs that are currently running
            (from PID files). Used to mark active runs correctly.
        error_on_inaccessible: If True, raise an OSError when the run
            directory does not exist or cannot be listed. Used in
            ``--json`` mode to signal that the data source is broken
            rather than silently returning empty results.

    Returns:
        List of run history dicts sorted by ``started_at`` descending,
        limited to ``recent``.

    Raises:
        OSError: When ``error_on_inaccessible`` is True and the run
            directory is missing or unreadable.
    """
    run_dir = _conductor_run_dir()
    if not run_dir.exists():
        if error_on_inaccessible:
            raise OSError(f"Run history directory does not exist: {run_dir}")
        return []
    if not run_dir.is_dir():
        if error_on_inaccessible:
            raise OSError(f"Run history path is not a directory: {run_dir}")
        return []

    try:
        log_files = sorted(
            run_dir.glob("conductor-*.events.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except (OSError, PermissionError) as exc:
        if error_on_inaccessible:
            raise OSError(f"Cannot list event logs in {run_dir}: {exc}") from exc
        logger.debug("Could not list event logs in %s", run_dir, exc_info=True)
        return []

    entries: list[dict[str, Any]] = []
    for lf in log_files:
        if len(entries) >= recent:
            break
        try:
            entry = _parse_event_log(lf, running_run_ids)
            if entry:
                entries.append(entry)
        except Exception:
            logger.debug("Could not parse event log: %s", lf, exc_info=True)

    entries.sort(key=lambda e: e["started_at"], reverse=True)
    return entries[:recent]


def _parse_event_log(log_file: Path, running_run_ids: set[str]) -> dict[str, Any] | None:
    """Parse a single JSONL event log file to derive run metadata.

    Reads the first valid JSON line for ``started_at`` and the last
    valid JSON line for ``ended_at`` and status. Tolerates truncated
    or malformed lines.

    The run ID is extracted from the filename:
    ``conductor-<workflow>-<timestamp>-<runid>.events.jsonl``

    Args:
        log_file: Path to a JSONL event log file.
        running_run_ids: Set of run IDs that are currently running.

    Returns:
        A run history dict or ``None`` if the file could not be parsed.
    """
    # Extract run_id from filename
    stem = log_file.stem  # e.g., "conductor-workflow-2025...-abc12345.events"
    # Remove suffix parts
    name_parts = stem.replace(".events", "").split("-")
    run_id = name_parts[-1] if len(name_parts) >= 2 else stem

    lines: list[dict[str, Any]] = []
    try:
        raw = log_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipping invalid JSON line in %s", log_file)
            continue

    if not lines:
        return None

    first = lines[0]
    last = lines[-1]

    # Derive workflow name from the first event
    workflow_name = "unknown"
    if first.get("type") == "workflow_started":
        data = first.get("data", {})
        # The workflow_started event uses "name" for the workflow name
        # (from self.config.workflow.name). Also check "workflow_name" as a
        # compatibility fallback for any older event shapes.
        workflow_name = data.get("name") or data.get("workflow_name") or log_file.stem

    started_at = _ts_to_iso(first.get("timestamp"))
    ended_at = None
    status = "running"

    last_type = last.get("type", "")
    if last_type == "workflow_completed":
        status = "completed"
        ended_at = _ts_to_iso(last.get("timestamp"))
    elif last_type == "workflow_failed":
        status = "failed"
        ended_at = _ts_to_iso(last.get("timestamp"))
    elif run_id in running_run_ids:
        status = "running"

    duration = None
    if started_at and ended_at:
        try:
            from datetime import datetime

            s = datetime.fromisoformat(started_at)
            e = datetime.fromisoformat(ended_at)
            duration = (e - s).total_seconds()
        except (ValueError, TypeError):
            pass

    return {
        "workflow": workflow_name,
        "run_id": run_id,
        "started_at": started_at or "?",
        "ended_at": ended_at,
        "status": status,
        "duration_seconds": duration,
        "log_file": str(log_file),
    }


def _ts_to_iso(ts: Any) -> str | None:
    """Convert a Unix timestamp to ISO-8601 string."""
    if ts is None:
        return None
    try:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _output_runs_json(
    running_entries: list[dict[str, Any]],
    history_entries: list[dict[str, Any]],
) -> None:
    """Emit running + history entries as a JSON array."""
    result: list[dict[str, Any]] = []
    for entry in running_entries:
        port = entry.get("port", "?")
        result.append(
            {
                "port": port,
                "pid": entry.get("pid"),
                "workflow": Path(entry.get("workflow", "?")).stem,
                "dashboard_url": f"http://127.0.0.1:{port}" if port != "?" else None,
                "started_at": entry.get("started_at"),
                "run_id": entry.get("run_id"),
                "status": "running",
            }
        )
    result.extend(history_entries)
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# `conductor list workflows`
# ---------------------------------------------------------------------------


@list_app.command("workflows")
def list_workflows(
    path: Annotated[
        Path,
        typer.Option(
            "--path",
            help="Root directory to search for workflow YAML files.",
        ),
    ] = Path.cwd(),  # noqa: B008
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            help="Walk subdirectories recursively.",
        ),
    ] = False,
    max_depth: Annotated[
        int,
        typer.Option(
            "--max-depth",
            help="Maximum recursion depth (only with --recursive). 0 = root only.",
            min=0,
        ),
    ] = 3,
    show_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show all YAML files (skip heuristic filtering).",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON instead of a table.",
        ),
    ] = False,
) -> None:
    """Discover workflow YAML files in the given directory.

    By default scans only the current directory (non-recursive) and
    filters out non-workflow YAML files using a heuristic check for
    ``agents:``, ``type: workflow``, or ``runtime:`` keys.

    Use ``--recursive`` to walk subdirectories and ``--all`` to skip
    the heuristic filter.
    """
    if not path.exists():
        console.print(
            f"[bold red]Error:[/bold red] Directory '[bold]{path}[/bold]' does not exist."
        )
        raise typer.Exit(code=1)
    if not path.is_dir():
        console.print(f"[bold red]Error:[/bold red] '[bold]{path}[/bold]' is not a directory.")
        raise typer.Exit(code=1)

    yaml_files = _discover_yaml_files(path, recursive, max_depth)
    metas = _heuristic_filter(yaml_files, show_all)

    if json_output:
        print(json.dumps(metas))
        return

    if not metas:
        output_console.print("[dim]No workflow files found.[/dim]")
        return

    table = Table(title="Local Workflows", show_lines=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Path", style="dim")
    table.add_column("Agents", style="green")
    table.add_column("Topology", style="yellow")
    for meta in metas:
        topology_parts = []
        if meta.get("has_parallel"):
            topology_parts.append("parallel")
        if meta.get("has_for_each"):
            topology_parts.append("for_each")
        if meta.get("has_pipeline"):
            topology_parts.append("pipeline")
        topology = ", ".join(topology_parts) if topology_parts else "—"
        table.add_row(
            meta["name"],
            meta["path"],
            str(meta.get("agent_count", 0)),
            topology,
        )
    output_console.print(table)


def _discover_yaml_files(root: Path, recursive: bool, max_depth: int) -> list[Path]:
    """Glob for ``*.yaml`` and ``*.yml`` files under ``root``.

    Args:
        root: Root directory to search.
        recursive: If True, walk subdirectories.
        max_depth: Maximum depth for recursive search.

    Returns:
        Sorted list of matching ``Path`` objects.
    """
    results: set[Path] = set()
    if recursive:
        for yf in root.rglob("*.yaml"):
            # Check depth
            depth = len(yf.relative_to(root).parts) - 1
            if depth <= max_depth:
                results.add(yf)
        for yf in root.rglob("*.yml"):
            depth = len(yf.relative_to(root).parts) - 1
            if depth <= max_depth:
                results.add(yf)
    else:
        results.update(root.glob("*.yaml"))
        results.update(root.glob("*.yml"))
    return sorted(results)


def _heuristic_filter(paths: list[Path], show_all: bool) -> list[dict[str, Any]]:
    """Filter YAML files to only those likely to be Conductor workflows.

    Reads the first 2 KB of each file and checks for ``agents:``,
    ``type: workflow``, or ``runtime:`` keys.

    Args:
        paths: List of YAML file paths.
        show_all: If True, include all files regardless of content.

    Returns:
        List of metadata dicts for matched files.
    """
    results: list[dict[str, Any]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")[:2048]
        except (OSError, UnicodeDecodeError):
            continue

        if not show_all and not (
            "agents:" in text or "type: workflow" in text or "runtime:" in text
        ):
            continue

        meta: dict[str, Any] = {
            "name": p.stem,
            "path": str(p.resolve()),
            "agent_count": 0,
            "has_parallel": False,
            "has_for_each": False,
            "has_pipeline": False,
        }

        # Try parsing with ruamel.yaml for richer metadata
        try:
            yaml_loader = YAML(typ="safe")
            parsed = yaml_loader.load(text)
            if isinstance(parsed, dict):
                wf = parsed.get("workflow", {})
                if isinstance(wf, dict):
                    meta["name"] = wf.get("name", p.stem)
                agents = parsed.get("agents", [])
                if isinstance(agents, (dict, list)):
                    meta["agent_count"] = len(agents)
                parallel = parsed.get("parallel", [])
                for_each = parsed.get("for_each", [])
                if isinstance(parallel, list) and parallel:
                    meta["has_parallel"] = True
                if isinstance(for_each, list) and for_each:
                    meta["has_for_each"] = True
                if (
                    meta["agent_count"] > 0
                    and not meta["has_parallel"]
                    and not meta["has_for_each"]
                ):
                    meta["has_pipeline"] = True
        except (YAMLError, Exception):
            pass  # Keep basic metadata from filename

        results.append(meta)
    return results


# ---------------------------------------------------------------------------
# `conductor list checkpoints`
# ---------------------------------------------------------------------------


@list_app.command("checkpoints")
def list_checkpoints(
    workflow: Annotated[
        Path | None,
        typer.Argument(
            help="Path to a workflow YAML file. Filters checkpoints to this workflow only.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON instead of a table.",
        ),
    ] = False,
) -> None:
    """List available workflow checkpoints.

    Shows all checkpoint files with metadata including workflow name,
    timestamp, failed agent, and error type. Optionally filter by
    workflow file.
    """
    _list_checkpoints_impl(workflow, json_output)


def _list_checkpoints_impl(workflow: Path | None, json_output: bool = False) -> None:
    """Shared implementation for ``list checkpoints`` and deprecated alias.

    Args:
        workflow: Optional workflow path filter (resolved to absolute).
        json_output: If True, emit JSON instead of Rich table.
    """
    # Resolve workflow path for filtering
    resolved_workflow: Path | None = None
    if workflow is not None:
        resolved_workflow = workflow.resolve()
        if not resolved_workflow.exists():
            error_console.print(f"[bold red]Error:[/bold red] Workflow file not found: {workflow}")
            raise typer.Exit(code=1)

    checkpoint_list = CheckpointManager.list_checkpoints(resolved_workflow)

    if json_output:
        json_data: list[dict[str, Any]] = []
        for cp in checkpoint_list:
            json_data.append(
                {
                    "version": cp.version,
                    "workflow_path": cp.workflow_path,
                    "workflow_hash": cp.workflow_hash,
                    "created_at": cp.created_at,
                    "failure": cp.failure,
                    "current_agent": cp.current_agent,
                    "run_id": cp.run_id,
                    "file_path": str(cp.file_path),
                }
            )
        print(json.dumps(json_data))
        return

    if not checkpoint_list:
        if resolved_workflow:
            output_console.print(
                f"[dim]No checkpoints found for workflow: {resolved_workflow.name}[/dim]"
            )
        else:
            output_console.print("[dim]No checkpoints found.[/dim]")
        return

    table = Table(title="Workflow Checkpoints", show_lines=True)
    table.add_column("Version", style="dim", justify="center")
    table.add_column("Workflow", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Error", style="red")
    table.add_column("Agent", style="yellow")

    for cp in checkpoint_list:
        version = str(cp.version)
        workflow_name = Path(cp.workflow_path).stem
        created = cp.created_at
        error = cp.failure.get("error_type", "unknown")
        agent = cp.failure.get("agent", "unknown")

        table.add_row(version, workflow_name, created, error, agent)

    output_console.print(table)
    output_console.print(f"\n[dim]Total: {len(checkpoint_list)} checkpoint(s)[/dim]")


# ---------------------------------------------------------------------------
# `conductor list registries`
# ---------------------------------------------------------------------------


@list_app.command("registries")
def list_registries(
    name: Annotated[
        str | None,
        typer.Argument(
            help="Name of a specific registry to list workflows from.",
        ),
    ] = None,
) -> None:
    """List configured registries or workflows within a specific registry.

    Delegates to the existing ``conductor registry`` commands.
    """
    from conductor.registry.errors import RegistryError

    try:
        if name is not None:
            from conductor.cli.registry import _list_registry_workflows

            _list_registry_workflows(name)
        else:
            from conductor.cli.registry import _list_all_registries

            _list_all_registries()
    except RegistryError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# `conductor list templates`
# ---------------------------------------------------------------------------


def _get_template_directories() -> list[Path]:
    """Return the list of directories to scan for templates.

    Currently returns the built-in templates directory if it exists.
    Plugin-provided template directories can be added here in the future.
    """
    dirs: list[Path] = []
    if _BUILTIN_TEMPLATES_DIR.is_dir():
        dirs.append(_BUILTIN_TEMPLATES_DIR)
    return dirs


@list_app.command("templates")
def list_templates(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON instead of a table.",
        ),
    ] = False,
) -> None:
    """List available workflow templates.

    Scans the built-in template directory (and any plugin-provided
    template directories) for YAML files with template metadata in
    their comment headers.

    Templates are YAML files whose first two comment lines follow the
    format::

        # Template Name (descriptive title)
        # Description (often "Use when: ...")
    """
    template_dirs = _get_template_directories()
    templates = _discover_templates(template_dirs)

    if json_output:
        print(json.dumps(templates))
        return

    if not templates:
        output_console.print("[dim]No templates found.[/dim]")
        return

    table = Table(title="Workflow Templates", show_lines=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Description", style="green")
    table.add_column("Path", style="dim")

    for t in templates:
        table.add_row(t["name"], t["description"], t["path"])

    output_console.print(table)
    output_console.print(f"\n[dim]Total: {len(templates)} template(s)[/dim]")
