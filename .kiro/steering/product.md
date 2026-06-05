# Product Overview

Conductor is a CLI tool for defining and running multi-agent workflows with the GitHub Copilot SDK and Anthropic Claude. It makes multi-agent workflows repeatable, deterministic, and version-controlled through YAML-based workflow definitions.

## Core Value Proposition

- **Repeatable** - Same inputs follow the same path through the same agents
- **Deterministic** - Routing uses Jinja2 templates and expression evaluation, no LLM in the orchestration loop
- **Source-controlled** - Plain YAML files that can be diffed, versioned, and run consistently

## Key Features

- YAML-based workflow definitions
- Multiple providers (GitHub Copilot, Anthropic Claude, Claude Agent SDK)
- Parallel execution (static groups and dynamic for-each)
- Sub-workflow composition with templated input mapping
- Script steps for shell command execution
- Set steps for binding Jinja2-evaluated values into context
- Terminate steps for explicit workflow termination
- Dialog mode for multi-turn conversation
- Reasoning effort control (low/medium/high/xhigh)
- Conditional routing between agents
- Human-in-the-loop gates with web dashboard support
- Real-time web dashboard for workflow visualization
- Safety limits (max iterations, timeout enforcement)
- Workflow registries for shared workflows
