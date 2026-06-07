# Workflow YAML Conventions

## Agents field: dict, not list
Conductor workflow YAML defines `agents:` as a **dict** of named agent
definitions (e.g., `agents:\n  researcher:\n    ...`), not as a list.
Code iterating over agents must handle `isinstance(agents, dict)` as the
primary case. `len(agents)` on a dict returns the number of named agent
entries.

## Heuristic workflow-detection keys
To distinguish workflow YAML from other YAML files (docker-compose, CI
configs, etc.), scan the first 2 KB of each `*.yaml`/`*.yml` file for
these substrings before attempting `yaml.safe_load`:
  - `agents:`
  - `type: workflow`
  - `runtime:`

This is an intentional performance optimization. Any command that scans
directories for workflow files should reuse this heuristic.
