# Typer CLI Patterns

## Path parameter validators and exit codes

Typer's `exists=True`, `dir_okay=True`, `file_okay=False` parameter
validators always exit with code 2 on failure and this cannot be
configured. When a feature requires exit code 1 (or any other specific
code), remove these validators from the `Option` decorator and perform
manual path validation in the function body, raising `typer.Exit(code=N)`
as needed.

See `list_workflows()` in `src/conductor/cli/list_cmd.py` for a working
example.
