All CLI modules route Rich console output to stderr by convention:
- `app.py:50`: `console = Console(stderr=True)`
- `list_cmd.py:34`: `console = Console(stderr=True)`
- `registry.py:35`: `console = Console(stderr=True)`

Deprecation notices, errors, and informational messages all go to stderr.
Only primary output (tables, JSON) goes to stdout via `output_console`.

In Typer CLI handler tests using CliRunner, `console.print()` goes to
stderr and `output_console.print()` goes to stdout. Deprecation notices
should use `console.print()` so they land on stderr and don't pollute
stdout for scripts.
