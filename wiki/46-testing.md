# 46 - Testing

The default command runs every test, including the exhaustive offline HTML
export checks:

```powershell
uv run pytest --basetemp .pytest_tmp
```

For a faster development loop, skip tests marked `full_export`:

```powershell
uv run pytest --basetemp .pytest_tmp -m "not full_export"
```

Run the exhaustive export boundary on its own before merging export, page,
plotting, or summary changes:

```powershell
uv run pytest --basetemp .pytest_tmp -m full_export
```

The repository uses pytest's built-in `tmp_path` fixture with the workspace-local
`--basetemp` above. Tests must not create persistent UUID-named directories at
the repository root.

Run the configured correctness lint before pushing:

```powershell
uv run ruff check .
```

`full_export` is reserved for behavior that requires every default dashboard
page and all dashboard states. Tests of writing, validation, individual pages,
selectors, and diagnostics should configure the smallest page and state set
that exercises their contract. This keeps those tests focused without reducing
the end-to-end coverage provided by the full-export tests.

## Which Suite To Run

| Change | During development | Before merge |
|---|---|---|
| Config, prepare, skimjoin, or isolated summary logic | Focused tests, then `-m "not full_export"` | Full default command |
| Page query or figure behavior | Focused page/figure tests, then fast suite | Fast suite plus `-m full_export` |
| Export serializer, payload, runtime, or state behavior | Focused export tests | Fast suite plus `-m full_export` |
| Documentation only | Link/catalog checks and focused documentation tests | Fast suite if CI does not provide a docs-only path |

The full-export tests are slow because they render every default page and
dashboard state into a representative standalone HTML document. The shared
fixture builds that document once per test session, so running the marked group
together avoids repeating the expensive render.

## Focused Commands

```powershell
uv run pytest --basetemp .pytest_tmp tests/test_page_authoring.py
uv run pytest --basetemp .pytest_tmp tests/test_figure_builders.py
uv run pytest --basetemp .pytest_tmp tests/test_export_serializer.py tests/test_export_payload.py
```

Use [Developer Workflows](40-developer-workflows.md) to choose tests by
subsystem.

## Related Chapters

- [40 - Developer Workflows](40-developer-workflows.md)
- [34 - HTML Export](34-html-export.md)
