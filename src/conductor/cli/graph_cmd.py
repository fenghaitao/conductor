"""Graph command — render workflow topology as Mermaid flowchart TD.

This module provides the ``conductor graph`` CLI command and the pure-function
``render_mermaid()`` renderer that converts a parsed ``WorkflowConfig`` into a
Mermaid ``flowchart TD`` diagram string with no side effects.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from conductor.config.loader import load_config
from conductor.exceptions import ConductorError

if TYPE_CHECKING:
    from conductor.config.schema import (
        AgentDef,
        RouteDef,
        WorkflowConfig,
    )

# ---------------------------------------------------------------------------
# Node shape templates by step type (index 0 = mermaid id, index 1 = label)
# ---------------------------------------------------------------------------
_NODE_SHAPES: dict[str, str] = {
    "agent": '{0}["{1}"]',  # rectangle
    "human_gate": "{0}{{{1}}}",  # rhombus
    "script": '{0}{{{{"{1}"}}}}',  # hexagon
    "set": '{0}(["{1}"])',  # stadium
    "wait": '{0}[("{1}")]',  # cylinder
    "terminate_success": '{0}("{1}")',  # rounded rect (via CSS)
    "terminate_failed": '{0}("{1}")',  # rounded rect (via CSS)
    "workflow": '{0}("{1}")',  # rounded rect (via CSS, opaque)
}

# CSS class assigned to each step type
_NODE_CLASSES: dict[str, str] = {
    "agent": "",
    "human_gate": "humanGate",
    "script": "scriptStep",
    "set": "setStep",
    "wait": "waitStep",
    "terminate_success": "terminateSuccess",
    "terminate_failed": "terminateFailed",
    "workflow": "workflowStep",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step_type(agent: AgentDef) -> str:
    """Return the canonical step-type key for *agent*.

    ``type: terminate`` is further qualified by ``status`` so that success
    and failure terminations get distinct shapes / CSS classes.
    """
    t = agent.type or "agent"
    if t == "terminate":
        status = agent.status or "success"
        return f"terminate_{status}"
    return t


def _node_label(agent: AgentDef) -> str:
    """Return a human-readable label for *agent*."""
    return agent.description or agent.name


def _topological_order(config: WorkflowConfig) -> dict[str, int]:
    """Compute a topological ordering of steps via BFS from ``entry_point``.

    Returns a dict mapping every reachable step name (agent, parallel group,
    for-each group) to its 0-indexed BFS depth.  Higher values appear later
    in the DAG.  Unreachable nodes are omitted from the result.

    The ordering is used by :func:`_is_loopback` to classify edges: an edge
    whose target has a depth ≤ the source's depth is a loop-back.
    """
    order: dict[str, int] = {}
    entry = config.workflow.entry_point
    order[entry] = 0

    # Build adjacency: name → [route targets excluding $end]
    adj: dict[str, list[str]] = {}
    all_names: set[str] = set()

    for agent in config.agents:
        all_names.add(agent.name)
        adj[agent.name] = [r.to for r in agent.routes if r.to != "$end"]

    for pg in config.parallel:
        all_names.add(pg.name)
        adj[pg.name] = [r.to for r in pg.routes if r.to != "$end"]
        for m in pg.agents:
            all_names.add(m)

    for fe in config.for_each:
        all_names.add(fe.name)
        adj[fe.name] = [r.to for r in fe.routes if r.to != "$end"]

    # BFS from entry point
    visited: set[str] = {entry}
    queue: list[str] = [entry]
    while queue:
        current = queue.pop(0)
        for target in adj.get(current, []):
            if target not in visited and target in all_names:
                visited.add(target)
                order[target] = order[current] + 1
                queue.append(target)

    return order


def _is_loopback(source: str, target: str, order: dict[str, int]) -> bool:
    """Return ``True`` when *source* → *target* is a loop-back edge.

    An edge is a loop-back when the target's topological depth is ≤ the
    source's depth.
    """
    src_o = order.get(source)
    tgt_o = order.get(target)
    if src_o is None or tgt_o is None:
        return False
    return tgt_o <= src_o


def _render_edge(source: str, route: RouteDef, order: dict[str, int]) -> str:
    """Render a single route as a Mermaid edge line."""
    target = "end" if route.to == "$end" else route.to
    arrow = "-.->" if _is_loopback(source, route.to, order) else "-->"
    if route.when:
        return f'{source} {arrow}|"{route.when}"| {target}'
    return f"{source} {arrow} {target}"


# ---------------------------------------------------------------------------
# Pure-function renderer
# ---------------------------------------------------------------------------


def render_mermaid(
    config: WorkflowConfig,
    depth: int = 1,
    parent_dir: Path | None = None,
    _visited: set[Path] | None = None,
) -> str:
    """Render a ``WorkflowConfig`` as a Mermaid ``flowchart TD`` diagram.

    **Pure function** — no I/O, no side effects, no provider calls.

    Args:
        config: Parsed workflow configuration from :func:`load_config`.
        depth: Remaining recursion depth for sub-workflow inlining
            (0 = opaque nodes only).
        parent_dir: Directory of the parent workflow file, used to resolve
            relative sub-workflow paths.
        _visited: Internal cycle-detection set of canonical resolved paths.
            Callers should not set this.

    Returns:
        Complete Mermaid ``flowchart TD`` diagram as a string (including
        trailing newline).
    """
    if _visited is None:
        _visited = set()

    lines: list[str] = []
    class_assignments: list[str] = []

    # ---- header -----------------------------------------------------------
    lines.append("flowchart TD")
    lines.append("  %% Generated by conductor graph")
    lines.append(f"  %% Workflow: {config.workflow.name}")
    lines.append(f"  %% Depth: {depth}")
    lines.append("")

    # ---- class definitions ------------------------------------------------
    lines.append("  classDef entryPoint stroke-width:3px")
    lines.append("  classDef humanGate stroke:#9c27b0,fill:#f3e5f5")
    lines.append("  classDef scriptStep stroke:#ff9800,fill:#fff3e0")
    lines.append("  classDef setStep stroke:#4caf50,fill:#e8f5e9")
    lines.append("  classDef waitStep stroke:#607d8b,fill:#eceff1")
    lines.append("  classDef terminateSuccess stroke:#2e7d32,fill:#e8f5e9")
    lines.append("  classDef terminateFailed stroke:#c62828,fill:#ffebee")
    lines.append("  classDef workflowStep stroke:#1565c0,fill:#e3f2fd,stroke-dasharray:5 5")
    lines.append("  classDef endNode stroke-width:2px")
    lines.append("  classDef errorNode stroke:#c62828,stroke-dasharray:5 5")
    lines.append("")

    # ---- topological order (for loop-back detection) ----------------------
    order = _topological_order(config)

    # ---- identify parallel-group members (rendered inside subgraphs) ------
    parallel_members: set[str] = set()
    for pg in config.parallel:
        parallel_members.update(pg.agents)

    entry_point = config.workflow.entry_point

    # ---- render regular agent nodes (not inside parallel groups) ----------
    for agent in sorted(config.agents, key=lambda a: a.name):
        if agent.name in parallel_members:
            continue

        stype = _step_type(agent)
        shape_tpl = _NODE_SHAPES.get(stype, _NODE_SHAPES["agent"])
        label = _node_label(agent)
        cls = _NODE_CLASSES.get(stype, "")

        node_line = f"  {shape_tpl.format(agent.name, label)}"
        lines.append(node_line)

        if cls:
            class_assignments.append(f"  class {agent.name} {cls}")

        # ---- sub-workflow inlining (depth > 0) ----------------------------
        if stype == "workflow" and depth > 0 and agent.workflow:
            sub_path = Path(agent.workflow)
            if parent_dir and not sub_path.is_absolute():
                sub_path = parent_dir / sub_path
            resolved = sub_path.resolve()

            if resolved in _visited:
                # Replace the opaque node with an error node
                lines.pop()
                lines.append(f'  {agent.name}["⚠️ Cycle: {agent.workflow}"]')
                class_assignments = [
                    ca for ca in class_assignments if not ca.endswith(f" {agent.name} workflowStep")
                ]
                class_assignments.append(f"  class {agent.name} errorNode")
            elif not resolved.exists():
                lines.pop()
                lines.append(f'  {agent.name}["⚠️ Missing: {agent.workflow}"]')
                class_assignments = [
                    ca for ca in class_assignments if not ca.endswith(f" {agent.name} workflowStep")
                ]
                class_assignments.append(f"  class {agent.name} errorNode")
            else:
                try:
                    sub_config = load_config(resolved)
                    # Build sub-workflow subgraph content
                    sub_lines = _render_subworkflow_subgraph(
                        sub_config,
                        depth - 1,
                        resolved.parent,
                        agent.name,
                        _visited | {resolved},
                    )
                    # Replace the opaque node line with subgraph block
                    lines.pop()
                    if cls:
                        class_assignments = [
                            ca
                            for ca in class_assignments
                            if not ca.endswith(f" {agent.name} workflowStep")
                        ]
                    lines.append("")
                    lines.extend(sub_lines)
                    lines.append("")
                except Exception:
                    lines.pop()
                    lines.append(f'  {agent.name}["⚠️ Error loading: {agent.workflow}"]')
                    class_assignments = [
                        ca
                        for ca in class_assignments
                        if not ca.endswith(f" {agent.name} workflowStep")
                    ]
                    class_assignments.append(f"  class {agent.name} errorNode")

    # ---- render parallel groups as subgraphs ------------------------------
    for pg in sorted(config.parallel, key=lambda p: p.name):
        lines.append(f'  subgraph {pg.name}["Parallel: {pg.name}"]')
        lines.append("    direction LR")
        for member_name in sorted(pg.agents):
            member = next((a for a in config.agents if a.name == member_name), None)
            if member:
                stype = _step_type(member)
                shape_tpl = _NODE_SHAPES.get(stype, _NODE_SHAPES["agent"])
                label = _node_label(member)
                cls = _NODE_CLASSES.get(stype, "")
                lines.append(f"    {shape_tpl.format(member_name, label)}")
                if cls:
                    class_assignments.append(f"  class {member_name} {cls}")
            else:
                lines.append(f'    {member_name}["{member_name}"]')
        lines.append("  end")
        lines.append("")

    # ---- render for-each groups as subgraphs ------------------------------
    for fe in sorted(config.for_each, key=lambda f: f.name):
        lines.append(f'  subgraph {fe.name}["For-Each: {fe.name} (source: {fe.source})"]')
        lines.append("    direction LR")
        inline = fe.agent
        stype = _step_type(inline)
        shape_tpl = _NODE_SHAPES.get(stype, _NODE_SHAPES["agent"])
        label = _node_label(inline)
        cls = _NODE_CLASSES.get(stype, "")
        lines.append(f"    {shape_tpl.format(inline.name, f'{label} (×N)')}")
        if cls:
            class_assignments.append(f"  class {inline.name} {cls}")
        lines.append("  end")
        lines.append("")

    # ---- $end node --------------------------------------------------------
    lines.append('  end(["$end"])')
    class_assignments.append("  class end endNode")
    lines.append("")

    # ---- edges ------------------------------------------------------------
    edges: list[str] = []

    for agent in sorted(config.agents, key=lambda a: a.name):
        if agent.name in parallel_members:
            continue
        for route in agent.routes:
            edges.append(_render_edge(agent.name, route, order))

    for pg in sorted(config.parallel, key=lambda p: p.name):
        for route in pg.routes:
            edges.append(_render_edge(pg.name, route, order))

    for fe in sorted(config.for_each, key=lambda f: f.name):
        for route in fe.routes:
            edges.append(_render_edge(fe.name, route, order))

    edges.sort()
    for edge in edges:
        lines.append(f"  {edge}")

    lines.append("")

    # ---- class assignments ------------------------------------------------
    for ca in sorted(class_assignments):
        lines.append(ca)

    # Entry-point highlight (always last so it overrides)
    lines.append(f"  class {entry_point} entryPoint")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sub-workflow inlining helpers
# ---------------------------------------------------------------------------


def _render_subworkflow_subgraph(
    config: WorkflowConfig,
    depth: int,
    parent_dir: Path,
    subgraph_id: str,
    _visited: set[Path],
) -> list[str]:
    """Render a sub-workflow as a Mermaid subgraph block.

    Returns a list of lines that can be spliced into the parent diagram
    in place of the opaque workflow node.
    """
    lines: list[str] = []
    class_assignments: list[str] = []

    lines.append(f'  subgraph {subgraph_id}["Workflow: {config.workflow.name}"]')
    lines.append("    direction LR")

    order = _topological_order(config)
    parallel_members: set[str] = set()
    for pg in config.parallel:
        parallel_members.update(pg.agents)

    # Nodes
    for agent in sorted(config.agents, key=lambda a: a.name):
        if agent.name in parallel_members:
            continue

        stype = _step_type(agent)
        shape_tpl = _NODE_SHAPES.get(stype, _NODE_SHAPES["agent"])
        label = _node_label(agent)
        cls = _NODE_CLASSES.get(stype, "")

        # Prefix node IDs to avoid collisions with parent diagram
        node_id = f"{subgraph_id}_{agent.name}"
        node_line = f"    {shape_tpl.format(node_id, label)}"
        lines.append(node_line)

        if cls:
            class_assignments.append(f"    class {node_id} {cls}")

        # Recursive sub-workflow inlining (depth permitting)
        if stype == "workflow" and depth > 0 and agent.workflow:
            sub_path = Path(agent.workflow)
            if not sub_path.is_absolute():
                sub_path = parent_dir / sub_path
            resolved = sub_path.resolve()

            if resolved in _visited:
                lines.pop()
                lines.append(f'    {node_id}["⚠️ Cycle: {agent.workflow}"]')
                class_assignments = [
                    ca for ca in class_assignments if not ca.endswith(f" {node_id} workflowStep")
                ]
                class_assignments.append(f"    class {node_id} errorNode")
            elif not resolved.exists():
                lines.pop()
                lines.append(f'    {node_id}["⚠️ Missing: {agent.workflow}"]')
                class_assignments = [
                    ca for ca in class_assignments if not ca.endswith(f" {node_id} workflowStep")
                ]
                class_assignments.append(f"    class {node_id} errorNode")
            else:
                try:
                    sub_config = load_config(resolved)
                    sub_lines = _render_subworkflow_subgraph(
                        sub_config,
                        depth - 1,
                        resolved.parent,
                        node_id,
                        _visited | {resolved},
                    )
                    lines.pop()
                    class_assignments = [
                        ca
                        for ca in class_assignments
                        if not ca.endswith(f" {node_id} workflowStep")
                    ]
                    lines.append("")
                    lines.extend(sub_lines)
                    lines.append("")
                except Exception:
                    lines.pop()
                    lines.append(f'    {node_id}["⚠️ Error loading: {agent.workflow}"]')
                    class_assignments = [
                        ca
                        for ca in class_assignments
                        if not ca.endswith(f" {node_id} workflowStep")
                    ]
                    class_assignments.append(f"    class {node_id} errorNode")

    # Parallel groups
    for pg in sorted(config.parallel, key=lambda p: p.name):
        pg_id = f"{subgraph_id}_{pg.name}"
        lines.append(f'    subgraph {pg_id}["Parallel: {pg.name}"]')
        lines.append("      direction LR")
        for member_name in sorted(pg.agents):
            member = next((a for a in config.agents if a.name == member_name), None)
            node_id = f"{subgraph_id}_{member_name}"
            if member:
                stype = _step_type(member)
                shape_tpl = _NODE_SHAPES.get(stype, _NODE_SHAPES["agent"])
                label = _node_label(member)
                cls = _NODE_CLASSES.get(stype, "")
                lines.append(f"      {shape_tpl.format(node_id, label)}")
                if cls:
                    class_assignments.append(f"    class {node_id} {cls}")
            else:
                lines.append(f'      {node_id}["{member_name}"]')
        lines.append("    end")

    # For-each groups
    for fe in sorted(config.for_each, key=lambda f: f.name):
        fe_id = f"{subgraph_id}_{fe.name}"
        lines.append(f'    subgraph {fe_id}["For-Each: {fe.name} (source: {fe.source})"]')
        lines.append("      direction LR")
        inline = fe.agent
        node_id = f"{subgraph_id}_{inline.name}"
        stype = _step_type(inline)
        shape_tpl = _NODE_SHAPES.get(stype, _NODE_SHAPES["agent"])
        label = _node_label(inline)
        cls = _NODE_CLASSES.get(stype, "")
        lines.append(f"      {shape_tpl.format(node_id, f'{label} (×N)')}")
        if cls:
            class_assignments.append(f"    class {node_id} {cls}")
        lines.append("    end")

    # $end node (prefixed)
    end_id = f"{subgraph_id}_end"
    lines.append(f'    {end_id}(["$end"])')
    class_assignments.append(f"    class {end_id} endNode")

    # Edges (prefixed)
    edges: list[str] = []
    for agent in sorted(config.agents, key=lambda a: a.name):
        if agent.name in parallel_members:
            continue
        src_id = f"{subgraph_id}_{agent.name}"
        for route in agent.routes:
            tgt = "end" if route.to == "$end" else route.to
            tgt_id = f"{subgraph_id}_end" if route.to == "$end" else f"{subgraph_id}_{tgt}"
            arrow = "-.->" if _is_loopback(agent.name, route.to, order) else "-->"
            if route.when:
                edges.append(f'    {src_id} {arrow}|"{route.when}"| {tgt_id}')
            else:
                edges.append(f"    {src_id} {arrow} {tgt_id}")

    for pg in sorted(config.parallel, key=lambda p: p.name):
        src_id = f"{subgraph_id}_{pg.name}"
        for route in pg.routes:
            tgt_id = f"{subgraph_id}_end" if route.to == "$end" else f"{subgraph_id}_{route.to}"
            arrow = "-.->" if _is_loopback(pg.name, route.to, order) else "-->"
            if route.when:
                edges.append(f'    {src_id} {arrow}|"{route.when}"| {tgt_id}')
            else:
                edges.append(f"    {src_id} {arrow} {tgt_id}")

    for fe in sorted(config.for_each, key=lambda f: f.name):
        src_id = f"{subgraph_id}_{fe.name}"
        for route in fe.routes:
            tgt_id = f"{subgraph_id}_end" if route.to == "$end" else f"{subgraph_id}_{route.to}"
            arrow = "-.->" if _is_loopback(fe.name, route.to, order) else "-->"
            if route.when:
                edges.append(f'    {src_id} {arrow}|"{route.when}"| {tgt_id}')
            else:
                edges.append(f"    {src_id} {arrow} {tgt_id}")

    edges.sort()
    for edge in edges:
        lines.append(f"  {edge}")

    # Class assignments and entry point
    for ca in sorted(class_assignments):
        lines.append(ca)

    entry_node_id = f"{subgraph_id}_{config.workflow.entry_point}"
    lines.append(f"    class {entry_node_id} entryPoint")

    lines.append("  end")

    return lines


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def graph(
    workflow: Annotated[
        str,
        typer.Argument(
            help="Workflow file path or registry reference (name[@registry][@version]).",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write diagram to file instead of stdout.",
        ),
    ] = None,
    depth: Annotated[
        int,
        typer.Option(
            "--depth",
            "-d",
            min=0,
            max=10,
            help="Sub-workflow inlining depth (0 = opaque nodes only).",
        ),
    ] = 1,
) -> None:
    """Render a workflow as a Mermaid flowchart TD diagram.

    Parses the workflow YAML and emits a static Mermaid ``flowchart TD``
    diagram to stdout (or ``--output FILE``).  No execution, no provider
    instantiation — pure static analysis.

    \b
    Examples:
        conductor graph workflow.yaml
        conductor graph workflow.yaml --output diagram.mmd
        conductor graph workflow.yaml --depth 0
        conductor graph qa-bot@team@1.0.0
    """
    from conductor.cli.app import print_error
    from conductor.registry.cache import resolve_and_fetch
    from conductor.registry.errors import RegistryError
    from conductor.registry.resolver import resolve_ref

    # ---- resolve input ----------------------------------------------------
    try:
        workflow_path = resolve_and_fetch(resolve_ref(workflow))
    except RegistryError as e:
        print_error(e)
        raise typer.Exit(code=1) from None

    # ---- load config ------------------------------------------------------
    try:
        config = load_config(workflow_path)
    except ConductorError as e:
        print_error(e)
        raise typer.Exit(code=1) from None
    except FileNotFoundError:
        print_error(FileNotFoundError(f"Workflow file not found: {workflow_path}"))
        raise typer.Exit(code=1) from None
    except Exception as e:
        print_error(e)
        raise typer.Exit(code=1) from None

    # ---- render -----------------------------------------------------------
    mermaid_text = render_mermaid(config, depth=depth, parent_dir=workflow_path.parent)

    # ---- output -----------------------------------------------------------
    if output:
        if not output.parent.exists():
            print_error(FileNotFoundError(f"Output directory does not exist: {output.parent}"))
            raise typer.Exit(code=1) from None
        try:
            output.write_text(mermaid_text)
        except OSError as e:
            print_error(e)
            raise typer.Exit(code=1) from None
    else:
        typer.echo(mermaid_text, nl=False)
