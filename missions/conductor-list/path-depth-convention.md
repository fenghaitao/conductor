# Path Depth Convention

The `_discover_yaml_files()` helper in `list_cmd.py` computes directory
depth as:

    depth = len(path.relative_to(root).parts) - 1

The `-1` offset accounts for the root directory itself (depth 0 at root).
Any path-handling code that needs to measure directory depth relative to a
search root must replicate this exact formula to avoid off-by-one
mismatches with `list workflows --max-depth`.
