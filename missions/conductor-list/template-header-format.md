## Template Header Format Convention

`_parse_template_headers()` in `src/conductor/cli/list_cmd.py` extracts
metadata from YAML template comment headers for the `conductor list
templates` command.

**Format contract:**

```yaml
# <Name>: <optional subtitle>
#
# Use when: <description>
```

- The **first comment line** becomes `name` (colon-separated subtitle
  included verbatim, e.g. `"Pipeline template: Sequential stages with
  conditional routing"`).
- The **first non-empty, non-separator comment** after the name line
  becomes `description`.
- Separator lines (`#` alone) are skipped.
- Files lacking this format return `None` and are silently excluded
  from the template listing.

**Discovered by:** implementation of `conductor list templates` (feature 6.2).
**Used by:** `_discover_templates()` in `list_cmd.py`.
