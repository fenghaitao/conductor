"""Tests for the ``conductor graph`` CLI command and ``render_mermaid()``.

This module covers:
- Unit tests for ``render_mermaid()`` pure function (in-memory ``WorkflowConfig``)
- Integration tests via ``CliRunner`` against example workflows
- Error handling (missing file, invalid YAML, schema violations)
- Golden-file comparisons against ``tests/fixtures/graph/*.mmd``
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from conductor.cli.app import app
from conductor.cli.graph_cmd import render_mermaid
from conductor.config.schema import (
    AgentDef,
    ForEachDef,
    ParallelGroup,
    RouteDef,
    WorkflowConfig,
    WorkflowDef,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers to build in-memory WorkflowConfig objects
# ---------------------------------------------------------------------------


def _make_workflow_config(
    name: str = "test",
    entry_point: str | None = None,
    agents: list[AgentDef] | None = None,
    parallel: list[ParallelGroup] | None = None,
    for_each: list[ForEachDef] | None = None,
) -> WorkflowConfig:
    """Build a minimal ``WorkflowConfig`` for unit tests.

    If *entry_point* is ``None``, it defaults to the first agent name
    (or the first parallel/for-each group name).
    """
    agents = agents or []
    parallel = parallel or []
    for_each = for_each or []

    if entry_point is None:
        if agents:
            entry_point = agents[0].name
        elif parallel:
            entry_point = parallel[0].name
        elif for_each:
            entry_point = for_each[0].name
        else:
            entry_point = "none"

    return WorkflowConfig(
        workflow=WorkflowDef(name=name, entry_point=entry_point),
        agents=agents,
        parallel=parallel,
        for_each=for_each,
    )


def _agent(
    name: str,
    type: str | None = None,
    description: str | None = None,
    routes: list[RouteDef] | None = None,
    workflow: str | None = None,
    status: str | None = None,
    prompt: str | None = None,
    options: list | None = None,
    command: str | None = None,
    value: str | None = None,
    duration: str | int | float | None = None,
    reason: str | None = None,
) -> AgentDef:
    """Build an ``AgentDef`` with type-appropriate required fields."""
    kwargs: dict = {
        "name": name,
        "description": description,
        "routes": routes or [],
        "workflow": workflow,
    }
    t = type or "agent"
    kwargs["type"] = t  # type: ignore[assignment]

    if t == "human_gate":
        kwargs["prompt"] = prompt or "gate prompt"
        kwargs["options"] = options or [{"label": "ok", "value": "ok", "route": "$end"}]
    elif t == "script":
        kwargs["command"] = command or "echo hello"
    elif t == "set":
        kwargs["value"] = value or "true"
    elif t == "wait":
        kwargs["duration"] = duration or "1s"
    elif t == "terminate":
        kwargs["status"] = status or "success"
        kwargs["reason"] = reason or "done"
    elif t == "workflow":
        kwargs["workflow"] = workflow or "sub.yaml"
    else:
        # Default agent — may still need prompt
        kwargs["prompt"] = prompt or "Do something"

    return AgentDef(**kwargs)  # type: ignore[arg-type]


def _route(to: str, when: str | None = None) -> RouteDef:
    """Build a ``RouteDef``."""
    return RouteDef(to=to, when=when)


# ---------------------------------------------------------------------------
# Unit tests — render_mermaid()
# ---------------------------------------------------------------------------


class TestRenderMermaidMinimal:
    """VAL-CORE-001: Basic rendering of minimal workflows."""

    def test_minimal_single_agent(self) -> None:
        """Single agent → one node, $end node, edge to $end."""
        config = _make_workflow_config(
            agents=[_agent("a1", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert "flowchart TD" in out
        assert 'a1["a1"]' in out
        assert '__end__(["$end"])' in out
        assert "a1 --> __end__" in out

    def test_entry_point_highlighted(self) -> None:
        """Entry point node gets ``entryPoint`` CSS class."""
        config = _make_workflow_config(
            entry_point="main",
            agents=[_agent("main", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert "class main entryPoint" in out

    def test_end_node_always_present(self) -> None:
        """$end node is always rendered regardless of whether any agent routes to it."""
        config = _make_workflow_config(
            agents=[_agent("a1", routes=[])],
        )
        out = render_mermaid(config)
        assert '__end__(["$end"])' in out
        assert "class __end__ endNode" in out

    def test_end_node_id_avoids_mermaid_reserved_keyword(self) -> None:
        """``$end`` must not be the bare id ``end`` — it collides with Mermaid's
        reserved ``end`` keyword that closes ``subgraph`` blocks, breaking the
        parser on any diagram that also contains a subgraph."""
        config = _make_workflow_config(
            entry_point="a1",
            agents=[
                _agent("a1", routes=[_route("pg")]),
                _agent("worker1"),
                _agent("worker2"),
            ],
            parallel=[
                ParallelGroup(
                    name="pg", agents=["worker1", "worker2"], routes=[RouteDef(to="$end")]
                ),
            ],
        )
        out = render_mermaid(config)
        # The only bare ``end`` tokens may be subgraph closers (a line that, once
        # stripped, equals exactly "end"). No node definition or edge may use it.
        assert 'end(["$end"])' not in out
        assert "--> end\n" not in out and "| end\n" not in out
        assert "class end endNode" not in out
        # Every "end" line is a subgraph closer.
        for line in out.splitlines():
            if line.strip() == "end":
                assert line.lstrip() == "end"

    def test_header_and_class_defs(self) -> None:
        """Output starts with ``flowchart TD`` and includes all classDef lines."""
        config = _make_workflow_config(
            agents=[_agent("a1", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        lines = out.splitlines()
        assert lines[0] == "flowchart TD"
        assert any("classDef entryPoint" in line for line in lines)
        assert any("classDef humanGate" in line for line in lines)
        assert any("classDef scriptStep" in line for line in lines)
        assert any("classDef setStep" in line for line in lines)
        assert any("classDef waitStep" in line for line in lines)
        assert any("classDef terminateSuccess" in line for line in lines)
        assert any("classDef terminateFailed" in line for line in lines)
        assert any("classDef workflowStep" in line for line in lines)
        assert any("classDef endNode" in line for line in lines)
        assert any("classDef errorNode" in line for line in lines)


class TestRenderMermaidShapes:
    """VAL-CROSS-003: Distinct node shapes for all step types."""

    def test_agent_shape_rectangle(self) -> None:
        config = _make_workflow_config(
            agents=[_agent("a1", type="agent", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert 'a1["a1"]' in out

    def test_human_gate_shape_rhombus(self) -> None:
        config = _make_workflow_config(
            agents=[_agent("gate", type="human_gate", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert 'gate{"gate"}' in out or "gate{gate}" in out
        assert "class gate humanGate" in out

    def test_script_shape_hexagon(self) -> None:
        config = _make_workflow_config(
            agents=[_agent("s1", type="script", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert 's1{{"s1"}}' in out
        assert "class s1 scriptStep" in out

    def test_set_shape_stadium(self) -> None:
        config = _make_workflow_config(
            agents=[_agent("set1", type="set", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert 'set1(["set1"])' in out
        assert "class set1 setStep" in out

    def test_wait_shape_cylinder(self) -> None:
        config = _make_workflow_config(
            agents=[_agent("w1", type="wait", routes=[_route("$end")])],
        )
        out = render_mermaid(config)
        assert 'w1[("w1")]' in out
        assert "class w1 waitStep" in out

    def test_terminate_success_shape(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("ok", type="terminate", status="success", routes=[]),
            ],
        )
        out = render_mermaid(config)
        assert 'ok("ok")' in out
        assert "class ok terminateSuccess" in out

    def test_terminate_failed_shape(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("fail", type="terminate", status="failed", routes=[]),
            ],
        )
        out = render_mermaid(config)
        assert 'fail("fail")' in out
        assert "class fail terminateFailed" in out

    def test_workflow_opaque_shape(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("sub", type="workflow", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config, depth=0)
        assert 'sub("sub")' in out
        assert "class sub workflowStep" in out

    def test_description_used_as_label(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("a1", description="Does the thing", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config)
        assert 'a1["Does the thing"]' in out


class TestRenderMermaidRoutes:
    """VAL-CROSS-004: Conditional edge labels and loop-back detection."""

    def test_unconditional_route_solid_edge(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("a1", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config)
        assert "a1 --> __end__" in out

    def test_conditional_route_labeled_edge(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("a1", routes=[_route("$end", when="score > 5")]),
            ],
        )
        out = render_mermaid(config)
        assert 'a1 -->|"score > 5"| __end__' in out

    def test_multiple_conditional_routes(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("start", routes=[_route("$end")]),
                _agent(
                    "a1",
                    routes=[
                        _route("a2", when="x == 1"),
                        _route("a3", when="x == 2"),
                        _route("$end"),
                    ],
                ),
                _agent("a2", routes=[_route("$end")]),
                _agent("a3", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config)
        assert 'a1 -->|"x == 1"| a2' in out
        assert 'a1 -->|"x == 2"| a3' in out
        assert "a1 --> __end__" in out

    def test_loop_back_detection_dotted_edge(self) -> None:
        """A → B → A: the return edge should be dotted."""
        config = _make_workflow_config(
            entry_point="check",
            agents=[
                _agent(
                    "check",
                    routes=[
                        _route("fix", when="bad"),
                        _route("$end", when="good"),
                    ],
                ),
                _agent(
                    "fix",
                    routes=[
                        _route("check"),
                    ],
                ),
            ],
        )
        out = render_mermaid(config)
        assert "fix -.-> check" in out
        assert 'check -->|"bad"| fix' in out or 'check -->|"bad"| fix' in out
        assert 'check -->|"good"| __end__' in out

    def test_loop_back_with_condition_dotted_labeled(self) -> None:
        """Loop-back with a condition should still be dotted."""
        config = _make_workflow_config(
            entry_point="review",
            agents=[
                _agent(
                    "review",
                    routes=[
                        _route("fix", when="needs_fix"),
                        _route("$end", when="ok"),
                    ],
                ),
                _agent(
                    "fix",
                    routes=[
                        _route("review", when="retry < 3"),
                    ],
                ),
            ],
        )
        out = render_mermaid(config)
        assert 'fix -.->|"retry < 3"| review' in out

    def test_edges_sorted_deterministically(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent(
                    "a1",
                    routes=[
                        _route("a2"),
                        _route("a3"),
                        _route("$end"),
                    ],
                ),
                _agent("a2", routes=[_route("$end")]),
                _agent("a3", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config)
        # Edges should appear sorted by source, then target
        idx_a1_a2 = out.index("a1 --> a2")
        idx_a1_a3 = out.index("a1 --> a3")
        idx_a1_end = out.index("a1 --> __end__")
        # ``__end__`` sorts before ``a2``/``a3`` ("_" < "a") lexicographically
        assert idx_a1_end < idx_a1_a2 < idx_a1_a3

    def test_no_orphan_edges(self) -> None:
        """Every edge target must exist as a node or $end."""
        config = _make_workflow_config(
            agents=[
                _agent("a1", routes=[_route("a2"), _route("$end")]),
                _agent("a2", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config)
        # All targets exist
        assert 'a1["a1"]' in out or "a1" in out
        assert 'a2["a2"]' in out or "a2" in out
        assert '__end__(["$end"])' in out
        assert "a1 --> a2" in out
        assert "a1 --> __end__" in out
        assert "a2 --> __end__" in out


class TestRenderMermaidGroups:
    """Parallel and for-each groups rendered as subgraphs."""

    def test_parallel_group_subgraph(self) -> None:
        config = _make_workflow_config(
            entry_point="pg",
            agents=[
                _agent("m1"),
                _agent("m2"),
            ],
            parallel=[
                ParallelGroup(
                    name="pg",
                    agents=["m1", "m2"],
                    routes=[RouteDef(to="$end")],
                ),
            ],
        )
        out = render_mermaid(config)
        assert 'subgraph pg["Parallel: pg"]' in out
        assert "direction LR" in out
        assert "m1" in out
        assert "m2" in out
        assert "  end" in out
        assert "pg --> __end__" in out

    def test_for_each_group_subgraph(self) -> None:
        config = _make_workflow_config(
            entry_point="fe",
            for_each=[
                ForEachDef(
                    **{  # type: ignore[arg-type]
                        "name": "fe",
                        "type": "for_each",
                        "source": "finder.output.items",
                        "as": "item",
                        "agent": _agent("worker"),
                        "routes": [RouteDef(to="$end")],
                    }
                ),
            ],
        )
        out = render_mermaid(config)
        assert 'subgraph fe["For-Each: fe' in out
        assert '(source: finder.output.items)"]' in out
        assert "direction LR" in out
        assert 'worker["worker (×N)"]' in out
        assert "fe --> __end__" in out


class TestRenderMermaidSubWorkflows:
    """Sub-workflow inlining, cycle detection, graceful degradation."""

    def test_depth_zero_opaque_node(self) -> None:
        """Depth 0: workflow agent rendered as opaque rounded rect."""
        config = _make_workflow_config(
            agents=[
                _agent("sub", type="workflow", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config, depth=0)
        assert 'sub("sub")' in out
        assert "class sub workflowStep" in out
        # No subgraph should be present
        assert "subgraph sub" not in out

    def test_depth_one_subworkflow_inlined(self, tmp_path: Path) -> None:
        """Depth 1 with existing sub-workflow file should inline as subgraph."""
        sub_path = tmp_path / "sub.yaml"
        sub_path.write_text(
            textwrap.dedent("""\
            workflow:
              name: sub-workflow
              entry_point: inner
            agents:
              - name: inner
                prompt: "Do it"
                routes:
                  - to: $end
            output:
              result: "{{ inner.output }}"
        """)
        )
        config = _make_workflow_config(
            agents=[
                _agent("sub", type="workflow", workflow=str(sub_path), routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config, depth=1, parent_dir=tmp_path)
        assert 'subgraph sub["Workflow: sub-workflow"]' in out
        assert "inner" in out

    def test_subworkflow_file_missing(self) -> None:
        """Missing sub-workflow file → error node, no crash."""
        config = _make_workflow_config(
            agents=[
                _agent(
                    "sub",
                    type="workflow",
                    workflow="nonexistent.yaml",
                    routes=[_route("$end")],
                ),
            ],
        )
        out = render_mermaid(config, depth=1)
        assert "⚠️ Missing: nonexistent.yaml" in out
        assert "class sub errorNode" in out

    def test_subworkflow_cycle_detection(self, tmp_path: Path) -> None:
        """Cyclic sub-workflow → error node, no infinite recursion."""
        sub_path = tmp_path / "self-ref.yaml"
        sub_path.write_text(
            textwrap.dedent(f"""\
            workflow:
              name: self-ref
              entry_point: inner
            agents:
              - name: inner
                type: workflow
                workflow: {sub_path}
                routes:
                  - to: $end
            output:
              result: "done"
        """)
        )
        config = _make_workflow_config(
            agents=[
                _agent("sub", type="workflow", workflow=str(sub_path), routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config, depth=5, parent_dir=tmp_path)
        # The cycle should be caught and an error node shown
        assert "⚠️ Cycle:" in out
        assert "class sub errorNode" in out or "class sub_" in out


class TestRenderMermaidDeterminism:
    """Deterministic output — same input produces identical output."""

    def test_deterministic_output(self) -> None:
        config = _make_workflow_config(
            agents=[
                _agent("c", routes=[_route("$end")]),
                _agent("a", routes=[_route("b"), _route("$end")]),
                _agent("b", routes=[_route("c")]),
            ],
        )
        out1 = render_mermaid(config)
        out2 = render_mermaid(config)
        assert out1 == out2

    def test_multiple_routes_sorted(self) -> None:
        """Edges are sorted lexicographically."""
        config = _make_workflow_config(
            agents=[
                _agent("a1", routes=[_route("z_target"), _route("a_target"), _route("$end")]),
                _agent("a_target", routes=[_route("$end")]),
                _agent("z_target", routes=[_route("$end")]),
            ],
        )
        out = render_mermaid(config)
        idx_a = out.index("a1 --> a_target")
        idx_end = out.index("a1 --> __end__")
        idx_z = out.index("a1 --> z_target")
        # ``__end__`` sorts before ``a_target`` ("_" < "a") lexicographically
        assert idx_end < idx_a < idx_z


# ---------------------------------------------------------------------------
# Integration tests — CliRunner
# ---------------------------------------------------------------------------


class TestGraphCLI:
    """VAL-CORE-001, VAL-CROSS-001: CLI integration tests."""

    def test_graph_help(self) -> None:
        result = runner.invoke(app, ["graph", "--help"])
        assert result.exit_code == 0
        assert "Render a workflow" in result.stdout
        assert "--output" in result.stdout
        assert "--depth" in result.stdout

    def test_graph_simple_qa(self) -> None:
        """VAL-CROSS-001: Linear workflow produces valid Mermaid."""
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml"])
        assert result.exit_code == 0
        assert "flowchart TD" in result.stdout
        assert "answerer" in result.stdout
        assert "$end" in result.stdout
        assert "classDef entryPoint" in result.stdout
        assert "answerer --> __end__" in result.stdout

    def test_graph_parallel_research(self) -> None:
        """Parallel groups render as subgraphs."""
        result = runner.invoke(app, ["graph", "examples/parallel-research.yaml"])
        assert result.exit_code == 0
        assert "flowchart TD" in result.stdout
        assert "subgraph parallel_researchers" in result.stdout
        assert "parallel_researchers --> synthesizer" in result.stdout

    def test_graph_for_each_simple(self) -> None:
        """For-each groups render as subgraphs."""
        result = runner.invoke(app, ["graph", "examples/for-each-simple.yaml"])
        assert result.exit_code == 0
        assert "subgraph item_processors" in result.stdout
        assert "(source: item_finder.output.topics)" in result.stdout
        assert "(×N)" in result.stdout

    def test_graph_terminate(self) -> None:
        """Terminate steps get distinct classes."""
        result = runner.invoke(app, ["graph", "examples/terminate.yaml"])
        assert result.exit_code == 0
        assert "class abort_unsafe terminateFailed" in result.stdout
        assert "class noop_exit terminateSuccess" in result.stdout

    def test_graph_script_step(self) -> None:
        """Script steps get hexagon shape."""
        result = runner.invoke(app, ["graph", "examples/script-step.yaml"])
        assert result.exit_code == 0
        assert "class check_python scriptStep" in result.stdout

    def test_graph_set_step(self) -> None:
        """Set steps get stadium shape."""
        result = runner.invoke(app, ["graph", "examples/set-step.yaml"])
        assert result.exit_code == 0
        assert "class compute_slug setStep" in result.stdout

    def test_graph_wait_step(self) -> None:
        """Wait steps get cylinder shape."""
        result = runner.invoke(app, ["graph", "examples/wait-step.yaml"])
        assert result.exit_code == 0
        assert "class cool_down waitStep" in result.stdout

    def test_graph_depth_zero(self) -> None:
        """--depth 0 produces output without subgraphs for workflow agents."""
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert "flowchart TD" in result.stdout

    def test_graph_depth_two(self) -> None:
        """--depth 2 is valid."""
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--depth", "2"])
        assert result.exit_code == 0
        assert "flowchart TD" in result.stdout

    def test_graph_output_file(self, tmp_path: Path) -> None:
        """--output writes to file, not stdout."""
        out_file = tmp_path / "test.mmd"
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--output", str(out_file)])
        assert result.exit_code == 0
        assert "flowchart TD" not in result.stdout
        assert out_file.exists()
        content = out_file.read_text()
        assert "flowchart TD" in content


class TestGraphCLIErrors:
    """VAL-CORE-002, VAL-CORE-003: Error handling."""

    def test_missing_file(self) -> None:
        """VAL-CORE-002: Missing file → exit 1, no traceback."""
        result = runner.invoke(app, ["graph", "nonexistent.yaml"])
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "flowchart TD" not in result.output

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """VAL-CORE-003: Malformed YAML → exit 1, no traceback."""
        bad = tmp_path / "bad.yaml"
        bad.write_text("this: [ is not valid yaml")
        result = runner.invoke(app, ["graph", str(bad)])
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "flowchart TD" not in result.output

    def test_schema_violation(self, tmp_path: Path) -> None:
        """VAL-CORE-003: Missing required field → exit 1, no traceback."""
        bad = tmp_path / "bad_schema.yaml"
        bad.write_text(
            textwrap.dedent("""\
            workflow:
              name: test
              # missing entry_point
            agents: []
        """)
        )
        result = runner.invoke(app, ["graph", str(bad)])
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "flowchart TD" not in result.output

    def test_missing_subworkflow_file_error_node(self, tmp_path: Path) -> None:
        """VAL-CORE-007: Missing sub-workflow file → exit 0, error node, no traceback."""
        wf = tmp_path / "parent.yaml"
        wf.write_text(
            textwrap.dedent("""\
            workflow:
              name: parent
              entry_point: main
            agents:
              - name: main
                prompt: "hello"
                routes:
                  - to: sub
              - name: sub
                type: workflow
                workflow: nonexistent-sub.yaml
                routes:
                  - to: $end
            output:
              result: "{{ sub.output }}"
        """)
        )
        result = runner.invoke(app, ["graph", str(wf), "--depth", "1"])
        assert result.exit_code == 0
        assert "Traceback" not in result.output
        assert "⚠️ Missing: nonexistent-sub.yaml" in result.stdout
        assert "class sub errorNode" in result.stdout
        assert "main" in result.stdout
        assert "$end" in result.stdout
        assert "flowchart TD" in result.stdout

    def test_cycle_subworkflow_error_node(self, tmp_path: Path) -> None:
        """VAL-CORE-007: Cyclic sub-workflow → exit 0, error node, no traceback."""
        wf = tmp_path / "self-ref.yaml"
        wf.write_text(
            textwrap.dedent(f"""\
            workflow:
              name: self-ref
              entry_point: main
            agents:
              - name: main
                prompt: "hello"
                routes:
                  - to: sub
              - name: sub
                type: workflow
                workflow: {wf}
                routes:
                  - to: $end
            output:
              result: "{{ sub.output }}"
        """)
        )
        result = runner.invoke(app, ["graph", str(wf), "--depth", "5"])
        assert result.exit_code == 0
        assert "Traceback" not in result.output
        assert "⚠️ Cycle:" in result.stdout
        assert "errorNode" in result.stdout
        assert "main" in result.stdout
        assert "$end" in result.stdout
        assert "flowchart TD" in result.stdout

    def test_depth_out_of_range_high(self) -> None:
        """Depth > 10 is rejected by Typer."""
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--depth", "11"])
        assert result.exit_code != 0

    def test_depth_out_of_range_negative(self) -> None:
        """Depth < 0 is rejected by Typer."""
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--depth", "-1"])
        assert result.exit_code != 0

    def test_output_to_nonexistent_dir(self, tmp_path: Path) -> None:
        """--output to non-existent parent dir → exit 1, no file created."""
        out_file = Path("/nonexistent/path/out.mmd")
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--output", str(out_file)])
        assert result.exit_code == 1
        assert "does not exist" in result.output
        assert "flowchart TD" not in result.stdout
        assert not out_file.exists()


class TestGraphGoldenFixtures:
    """Golden-file comparisons against tests/fixtures/graph/*.mmd."""

    FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "graph"

    def test_golden_simple_qa_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "simple-qa-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_simple_qa_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "simple-qa-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/simple-qa.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_parallel_research_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "parallel-research-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/parallel-research.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_parallel_research_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "parallel-research-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/parallel-research.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_for_each_simple_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "for-each-simple-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/for-each-simple.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_for_each_simple_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "for-each-simple-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/for-each-simple.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_terminate_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "terminate-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/terminate.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_terminate_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "terminate-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/terminate.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_script_step_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "script-step-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/script-step.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_script_step_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "script-step-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/script-step.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_set_step_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "set-step-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/set-step.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_set_step_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "set-step-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/set-step.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_wait_step_depth0(self) -> None:
        golden = self.FIXTURE_DIR / "wait-step-depth0.mmd"
        result = runner.invoke(app, ["graph", "examples/wait-step.yaml", "--depth", "0"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()

    def test_golden_wait_step_depth1(self) -> None:
        golden = self.FIXTURE_DIR / "wait-step-depth1.mmd"
        result = runner.invoke(app, ["graph", "examples/wait-step.yaml", "--depth", "1"])
        assert result.exit_code == 0
        assert result.stdout == golden.read_text()
