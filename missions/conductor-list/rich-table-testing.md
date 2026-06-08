## Rich Table Output in Pytest Capture Mode

Rich `Table` objects truncate or wrap column content when stdout is not
a TTY (e.g. pytest capture mode via `CliRunner`). Long cell values may
be split across multiple lines, making exact string matching unreliable.

**Workaround:** Fragment match using the first token before the colon
(`name.split(":")[0]`) to verify table/JSON consistency.

**Alternative:** Set `COLUMNS` env var or `width` on the `Console`
instance to force wide output and avoid truncation:

```python
Console(width=200)
# or
os.environ["COLUMNS"] = "200"
```

**Discovered by:** testing `conductor list templates` table output (feature 6.3).
**Relevant files:** `tests/test_cli/test_list.py` — `test_json_array_length_matches_table_rows`,
`test_json_and_table_names_same_order`.
