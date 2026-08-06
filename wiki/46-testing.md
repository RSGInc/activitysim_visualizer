# 46 - Testing

The default command runs all tests, including the complete offline HTML export
checks:

```powershell
uv run pytest --basetemp .pytest_tmp
```

For a faster development test, omit tests marked `full_export`:

```powershell
uv run pytest --basetemp .pytest_tmp -m "not full_export"
```

Run the complete export tests before merging export, page, plotting, or summary
changes:

```powershell
uv run pytest --basetemp .pytest_tmp -m full_export
```

The repository uses pytest's built-in `tmp_path` fixture with the
workspace-local `--basetemp` value above. Tests must not create persistent
UUID-named directories in the repository root.

Run this correctness check before pushing changes:

```powershell
uv run ruff check .
```

Use `full_export` only for behavior that requires all default dashboard pages
and dashboard states. For writes, validation, pages, selectors, and diagnostics,
configure the smallest relevant page and state set. The full-export tests still
provide complete workflow coverage.

## Which Suite To Run

| Change | During development | Before merge |
|---|---|---|
| Config, prepare, skimjoin, or isolated summary logic | Focused tests, then `-m "not full_export"` | Full default command |
| Page query or figure behavior | Focused page/figure tests, then fast suite | Fast suite plus `-m full_export` |
| Export serializer, payload, runtime, or state behavior | Focused export tests | Fast suite plus `-m full_export` |
| Documentation only | Link/catalog checks and focused documentation tests | Fast suite if CI does not provide a docs-only path |

The full-export tests take longer because they render every default page and
dashboard state in one representative standalone HTML document. A shared
fixture builds the document once per test session, so run the marked group
together to avoid repeated renders.

## Focused Commands

```powershell
uv run pytest --basetemp .pytest_tmp tests/test_page_authoring.py
uv run pytest --basetemp .pytest_tmp tests/test_figure_builders.py
uv run pytest --basetemp .pytest_tmp tests/test_export_serializer.py tests/test_export_payload.py
```

Use [Developer Workflows](40-developer-workflows.md) to select tests for a
subsystem.

## Related Chapters

- [40 - Developer Workflows](40-developer-workflows.md)
- [34 - HTML Export](34-html-export.md)
