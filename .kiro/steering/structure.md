# Project Structure

## Root Directory

```
conductor/
├── src/conductor/        # Main source code
├── tests/                # Test suite (mirrors src structure)
├── docs/                 # Documentation
├── examples/             # Example workflows
├── conductor-ts/         # TypeScript packages (CLI, VS Code extension)
├── plugins/              # Plugin marketplace and skills
├── .kiro/                # Kiro configuration
├── .github/              # GitHub workflows, skills, prompts
└── pyproject.toml        # Project configuration
```

## Source Code Structure (`src/conductor/`)

### Core Modules

- **`cli/`** - Typer-based CLI commands
  - `app.py` - Main entry point
  - `run.py` - Workflow execution command
  - `bg_runner.py` - Background process forking for `--web-bg`
  - `pid.py` - PID file utilities
  - `update.py` - Update check and version comparison

- **`config/`** - YAML loading and validation
  - `schema.py` - Pydantic models for workflow YAML
  - `loader.py` - YAML parsing with env vars and `!file` tag
  - `validator.py` - Cross-reference validation

- **`engine/`** - Workflow execution orchestration
  - `workflow.py` - Main `WorkflowEngine` class
  - `context.py` - `WorkflowContext` for accumulated outputs
  - `router.py` - Route evaluation (Jinja2/simpleeval)
  - `limits.py` - Safety enforcement
  - `checkpoint.py` - Checkpoint save/resume

- **`executor/`** - Agent and step execution
  - `agent.py` - Single agent execution
  - `script.py` - Shell command execution
  - `set_step.py` - Jinja2 expression binding
  - `wait.py` - Duration-based pausing
  - `template.py` - Jinja2 rendering
  - `output.py` - JSON output parsing

- **`providers/`** - AI provider implementations
  - `base.py` - `AgentProvider` ABC
  - `copilot.py` - GitHub Copilot SDK
  - `claude.py` - Anthropic Claude API
  - `claude_agent_sdk.py` - Claude Agent SDK
  - `factory.py` - Provider instantiation
  - `capabilities.py` - Provider capability descriptors

- **`gates/`** - Human-in-the-loop support
  - `human.py` - Rich terminal UI

- **`interrupt/`** - Interactive interruption (Esc/Ctrl+G)
  - `listener.py` - Keyboard listener daemon

- **`web/`** - Real-time web dashboard
  - `server.py` - FastAPI + WebSocket server
  - `static/` - Single-file Cytoscape.js frontend

- **`mcp/`** - Model Context Protocol support

- **`registry/`** - Workflow registry management

### Top-Level Modules

- **`events.py`** - Pub/sub event system
- **`exceptions.py`** - Custom exception hierarchy
- **`duration.py`** - Duration parsing helper

## Test Structure (`tests/`)

Mirrors source structure:

- `test_cli/` - CLI command tests, e2e tests
- `test_config/` - Schema validation, loader tests
- `test_engine/` - Workflow, router, context, limits tests
- `test_executor/` - Agent, template, output tests
- `test_providers/` - Provider implementation tests
- `test_integration/` - Full workflow execution tests
- `test_gates/` - Human gate tests

## Documentation (`docs/`)

- `workflow-syntax.md` - Complete YAML schema reference
- `cli-reference.md` - Full CLI documentation
- `parallel-execution.md` - Static parallel groups
- `dynamic-parallel.md` - For-each groups
- `providers/` - Provider-specific documentation
- `design/` - Design documents (registry, etc.)

## Examples (`examples/`)

Sample workflows demonstrating features:
- `simple-qa.yaml` - Basic single-agent
- `for-each-simple.yaml` - Dynamic parallel
- `parallel-research.yaml` - Static parallel
- `design-review.yaml` - Human gate with loop
- `script-step.yaml` - Shell command execution
- `set-step.yaml` - Value binding
- `wait-step.yaml` - Duration pausing
- `terminate.yaml` - Explicit termination

## TypeScript Packages (`conductor-ts/`)

- `packages/conductor-cli/` - TypeScript CLI
- `packages/conductor-core/` - Core TypeScript library
- `packages/conductor-vscode/` - VS Code extension

## Plugins (`plugins/`)

- `conductor/skills/conductor/` - Conductor skill for Claude Code/Copilot CLI
