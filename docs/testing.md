# Testing

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
