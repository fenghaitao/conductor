# YAML `agents:` Key — Dual Form

The `agents:` key in Conductor workflow YAML can be either:
- A **dict** (named agent definitions): `agents: { researcher: {...}, writer: {...} }`
- A **list** (inline agent definitions): `agents: [{...}, {...}]`

Any code that scans YAML files for agent definitions must handle both forms.
The canonical pattern is:
```python
agents = top.get("agents")
if isinstance(agents, (dict, list)):
    agent_count = len(agents)
```

Discovered during `conductor list workflows` implementation (milestone
list-workflows, feature 3.1). Previously `_heuristic_filter` only handled the
list form, causing dict-form workflows to be incorrectly filtered.
