# CLI Output Contracts

## `list workflows` output

- **Table mode**: Paths are always absolute regardless of whether
  `--path` was given as relative.
- **`--recursive`**: Output includes absolute paths for files in
  subdirectories up to `--max-depth` (default 3).

## `--json` output contract

The JSON array emitted by `list workflows --json` must contain objects
with exactly these keys:
  - `name`
  - `path`
  - `agent_count`
  - `has_parallel`
  - `has_for_each`
  - `has_pipeline`

`description` is intentionally omitted. Output must be parseable by
`jq` and `json.loads()` — no Rich markup, no ANSI escapes. Empty state
yields `[]`.
