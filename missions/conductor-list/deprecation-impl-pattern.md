When deprecating a top-level command in favour of a subcommand under
`list`, the canonical pattern is:

1. Create a shared `_list_*_impl()` function in `list_cmd.py` that
   contains the actual logic and writes to `output_console` (stdout for
   tables) or `print()` (for JSON).
2. The new `list <subcommand>` handler in `list_cmd.py` delegates to
   this impl function.
3. The deprecated top-level command in `app.py` prints a `[dim]`
   deprecation notice to `console` (stderr) then delegates to the same
   impl function.

Example: `_list_checkpoints_impl(workflow, json_output)` at
`list_cmd.py:761` is the canonical checkpoint-listing implementation.
Both `list checkpoints` (line 737) and the deprecated `checkpoints`
(app.py:988) delegate to it. Any future changes to checkpoint listing
should modify this single function.
