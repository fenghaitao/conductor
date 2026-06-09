# Rich Console Pattern for CLI Commands

List subcommand modules must use two Rich `Console` instances:
  - `console` (stderr) — error messages and deprecation warnings
  - `output_console` (stdout) — primary table/JSON output

This separation ensures scriptable `--json` output on stdout is never
polluted by diagnostic or error text. Every new `list` subcommand must
follow this pattern.
