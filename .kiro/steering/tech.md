# Technology Stack

## Language & Runtime

- **Python 3.12+** - Modern Python with type hints
- **uv** - Fast dependency management and virtual environment tool

## Build System

Uses `uv` for dependency management with `hatchling` as the build backend.

### Common Commands

```bash
# Install dependencies
make install          # or: uv sync
make dev              # install with dev dependencies

# Run tests
make test                                           # all tests
uv run pytest tests/test_engine/test_workflow.py   # single file
uv run pytest -k "test_parallel"                   # pattern match

# Run tests with coverage
make test-cov

# Lint and format
make lint             # check only
make format           # auto-fix and format

# Type check
make typecheck

# Run all checks (lint + typecheck)
make check

# Build package
make build

# Validate example workflows
make validate-examples
```

## Core Dependencies

### CLI & UI
- **typer** - CLI framework
- **rich** - Terminal UI and formatting

### Configuration & Validation
- **pydantic v2** - Data validation and settings management
- **ruamel.yaml** - YAML parsing with environment variable resolution
- **jinja2** - Template rendering
- **simpleeval** - Safe expression evaluation

### AI Providers
- **github-copilot-sdk** - GitHub Copilot integration
- **anthropic** - Claude API integration
- **claude-agent-sdk** (optional) - Claude Agent SDK integration

### Web & Networking
- **fastapi** - Web framework for dashboard
- **uvicorn** - ASGI server
- **websockets** - Real-time communication
- **httpx** - HTTP client

### Other
- **mcp** - Model Context Protocol support
- **packaging** - Version handling

## Development Dependencies

- **pytest** - Testing framework with async support
- **pytest-asyncio** - Async test support
- **pytest-cov** - Coverage reporting
- **ruff** - Fast linter and formatter
- **ty** - Type checker (Red Knot)

## Code Style

- **Line length**: 100 characters
- **Formatting**: Ruff (Black-compatible)
- **Linting**: Ruff with rules E, W, F, I, B, C4, UP, SIM
- **Docstrings**: Google-style
- **Type hints**: Required, checked with ty

## Testing

- **Framework**: pytest with `asyncio_mode = "auto"`
- **Structure**: Tests mirror source structure in `tests/`
- **Markers**:
  - `performance` - Exclude with `-m "not performance"`
  - `real_api` - Tests making real API calls
  - `install_scripts` - Slow install script tests

## Project Scripts

The CLI entry point is `conductor = "conductor.cli.app:app"`
