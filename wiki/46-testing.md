# 46 - Testing

## Install Test Dependencies

The project supports Python 3.10 or later. The checked-in GitHub Actions job
uses Python 3.12 on Windows. Install the locked runtime and `dev` dependency
group before running its commands:

```powershell
uv sync --locked --group dev
```

The `dev` group contains `pytest` and `ruff`. The separate `notebooks` group is
not required for the test suite. Do not add an ad hoc `--with` dependency when
the locked development environment is already installed.

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

## Match Continuous Integration

`.github/workflows/tests.yml` runs on pushes to `main`, pull requests, and
manual dispatch. It checks out the repository, selects Python 3.12, installs
`uv`, syncs the locked `dev` group, runs Ruff, and then runs the full pytest
command. To reproduce the CI work locally:

```powershell
uv sync --locked --group dev
uv run ruff check .
uv run pytest --basetemp .pytest_tmp
```

CI currently has no separate docs-link job. Documentation changes that add or
rename pages must therefore run the repository's catalog generator and a local
Markdown link/anchor check in addition to the relevant Python tests.

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

## Generated Runtime And Catalog Checks

The browser export runtime has readable source under
`dashboard/export/js_runtime/` and a generated artifact at
`dashboard/export/assets/export_runtime.js`. After changing the readable
source, rebuild it and run its contract test:

```powershell
uv run python dashboard/export/build_export_runtime.py
uv run pytest --basetemp .pytest_tmp tests/test_export_runtime_build.py tests/test_export_runtime_contract.py
```

The build test checks that the tracked generated asset matches the runtime
source. If it fails, rebuild the asset and commit the generated change. Do not
edit the asset directly.

After changing summary declarations, schemas, summary catalog metadata, page
definitions, groups, or page data requirements, regenerate and test the wiki
catalogs and standalone processor output reference. Changes to prepared-output
or sidecar contracts also require regeneration:

```powershell
uv run python scripts/generate_wiki_catalogs.py
uv run pytest --basetemp .pytest_tmp tests/test_summary_declarations.py tests/test_page_registry_contract.py
```

Review the generated diff. A catalog change should follow the code contract
that caused it; do not hand-edit generated blocks.

## Test Data Conventions

- Build the smallest Polars frames that exercise the contract. Include only
  the IDs, source fields, and `finalweight` needed by the behavior.
- Use `tmp_path` for files and `tmp_path_factory` only for intentionally shared
  session fixtures. Never create persistent test output in the repository
  root.
- Write CSV, Parquet, OMX, or YAML inputs inside that temporary directory.
- Give IDs explicit compatible types when a join or cache schema is under test.
- Test the complete case plus the relevant empty, unavailable, failed, orphan,
  or partial-run case.
- Keep pure summary/transform assertions independent of Panel. Add lifecycle or
  export tests only for behavior at those boundaries.
- Reuse the session-scoped `representative_full_export_html` fixture when a
  test genuinely needs the full default export. Do not rebuild it in each
  test.

When a regression needs a large real data set, reduce it to a small synthetic
fixture or store only a reviewed stable fixture under `tests`. Tests must not
depend on a developer's model-output directory, network service, or existing
cache root.

Use [Developer Workflows](40-developer-workflows.md) to select tests for a
subsystem.

## Related Chapters

- [40 - Developer Workflows](40-developer-workflows.md)
- [34 - HTML Export](34-html-export.md)
