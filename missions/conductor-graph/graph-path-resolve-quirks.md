# graph_cmd.py Path.resolve() quirks

## _visited cycle detection

Python Path objects hash by resolved string, so `Path('a/b/../c').resolve() == Path('c').resolve()` works correctly for cycle detection.

## Broken symlink edge case

`Path.resolve()` raises `OSError` on broken symlinks. In `graph_cmd.py`, `resolved = sub_path.resolve()` at ~line 399 occurs outside the `except Exception` block that wraps sub-workflow processing. If a sub-workflow path contains a broken symlink, this raises before the exists/cycle check, causing an unhandled exception not caught by the bare `except Exception` at line 434.

## Bare except Exception

`graph_cmd.py` uses bare `except Exception` at lines 266 and 434 for 'never crash' semantics. This is correct per the feature spec but could silently swallow unexpected Python errors (e.g., KeyboardInterrupt). A future refinement could log a warning for non-ConductorError exceptions before rendering the error node.
