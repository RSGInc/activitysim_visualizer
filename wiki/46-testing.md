# 46 - Testing

The default command executes all tests. It includes the complete offline HTML
export checks:

```powershell
uv run pytest --basetemp .pytest_tmp
```

For a faster development test, omit tests marked `full_export`:

```powershell
uv run pytest --basetemp .pytest_tmp -m "not full_export"
```

Execute the complete export tests before you merge export, page, plotting, or
summary changes:

```powershell
uv run pytest --basetemp .pytest_tmp -m full_export
```

The repository uses the built-in pytest `tmp_path` fixture. It uses the
workspace-local `--basetemp` value above. Tests must not create persistent
UUID-named directories in the repository root.

Execute this correctness check before you push changes:

```powershell
uv run ruff check .
```

Use `full_export` only for behavior that requires all default dashboard pages
and dashboard states. For writes, validation, pages, selectors, and diagnostics,
configure the smallest applicable page and state set. The full-export tests
continue to supply complete workflow coverage.

## Which Suite To Run

| Change | During development | Before merge |
|---|---|---|
| Config, prepare, skimjoin, or isolated summary logic | Focused tests, then `-m "not full_export"` | Full default command |
| Page query or figure behavior | Focused page/figure tests, then fast suite | Fast suite plus `-m full_export` |
| Export serializer, payload, runtime, or state behavior | Focused export tests | Fast suite plus `-m full_export` |
| Documentation only | Link/catalog checks and focused documentation tests | Fast suite if CI does not provide a docs-only path |

The full-export tests render each default page and dashboard state in one
representative standalone HTML document. Thus, these tests take more time. The
shared fixture builds the document one time in each test session. Execute the
marked group together to prevent repeated renders.

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
