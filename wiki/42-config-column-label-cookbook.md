# 42 - Config, Columns, And Labels

This chapter shows how one YAML value travels through validation, typed config,
cache identity, prepared data, and dashboard presentation.

## First Decide Which Boundary Owns The Setting

| Setting changes... | Put it under... | Signature impact |
|---|---|---|
| prepared rows or columns | `prepare` or `columns` | Prepare, and usually summary downstream |
| summary values or grouping | `summarize` | Summary |
| labels, ordering, colors, or page appearance | `display` or `dashboard` | Presentation |
| which workflow executes | `pipeline` | Runtime plan; include data effects in the owning signature too |

Do not add a setting only to `Config`. A complete setting has validation,
normalization, a typed field, cache/signature ownership, a consumer, an example,
and tests.

## Worked Example: Add A New Config Item

Suppose the dashboard needs a presentation-only switch:

```yaml
display:
  show_zero_categories: true
```

### 1. Validate The Key

Add it to the `display` allow-list in `runtime/config/schema.py`:

```python
_reject_unknown_keys(
    display,
    field_name="display",
    allowed={
        # existing keys...
        "show_zero_categories",
    },
)
```

### 2. Normalize Once In The Loader

In `runtime/config/loader.py`, reject YAML values that are not booleans:

```python
show_zero_categories = display_cfg.get("show_zero_categories", False)
if not isinstance(show_zero_categories, bool):
    raise ValueError(
        "display.show_zero_categories must be true or false when provided."
    )
```

Pass it into `Config(...)` and add the typed field in
`runtime/config/models.py`:

```python
@dataclass
class Config:
    # existing fields...
    show_zero_categories: bool
```

Downstream code should read `config.show_zero_categories`, never the raw YAML
mapping.

### 3. Put It In The Correct Signature

Because this switch changes only rendering, add it to
`presentation_signature_payload()` in `runtime/config/signatures.py`:

```python
return {
    # existing presentation values...
    "show_zero_categories": config.show_zero_categories,
}
```

Do not add it to the prepare or summary signatures. That would cause expensive
cache rebuilds for a display-only change.

### 4. Consume It At The Presentation Boundary

For example, a shared category helper can choose whether to complete absent
categories:

```python
if config.show_zero_categories:
    chart_data = complete_category_rows(chart_data, expected_categories)
```

Prefer a shared helper if several pages need the setting. Keep one-off behavior
on the owning page.

### 5. Document And Test It

Update `config.yaml` and chapter 13. Add tests for the default, explicit value,
wrong type, signature ownership, and visible consumer behavior:

The snippets below use illustrative module-local helpers named
`_write_config()` and `_raw_run()`. They are not repository-wide pytest
fixtures: define the minimal helper in the owning test module, or adapt that
module's existing config/run factory. Likewise, `extra_lines` and
`column_lines` are example helper arguments rather than public config APIs.

```python
def test_show_zero_categories_is_presentation_only(tmp_path):
    config = _write_config(
        tmp_path,
        extra_lines=["display:", "  show_zero_categories: true"],
    )
    assert config.show_zero_categories is True
    assert "show_zero_categories" in config.presentation_signature_payload()
    assert "show_zero_categories" not in config.prepare_signature_payload()
    assert "show_zero_categories" not in config.summary_signature_payload()
```

## Worked Example: Wire A Configured Column Name Into Prepare

Suppose different models call household area type `area_type`, `ATYPE`, or
`area_class`. The prepared contract should expose one stable name:
`area_type`.

### 1. Add The Alias Setting

Add one entry to `_ALIAS_COLUMN_DEFAULTS` in `runtime/config/sections.py`:

```python
_ALIAS_COLUMN_DEFAULTS = {
    # existing aliases...
    "col_area_type": (
        "area_type",
        ["area_type", "ATYPE", "area_class"],
    ),
}
```

`CANONICAL_COLUMN_KEYS` is derived from this mapping, so
`columns.area_type` becomes valid automatically. Add the typed field to
`Config`:

```python
col_area_type: list[str]
```

The user can now override precedence:

```yaml
columns:
  area_type: [area_class, ATYPE]
```

The first available candidate wins.

### 2. Materialize The Canonical Column

In `processor/prepare/enrichment/canonicalize.py`:

```python
def _canonicalize_households(hh: pl.DataFrame, config: Config) -> pl.DataFrame:
    # existing canonical columns...
    return _materialize_column(
        hh,
        "area_type",
        _resolve_source_column(hh, config.col_area_type),
    )
```

Keep the configured source candidates in config and the stable output name in
prepare. Summary builders should require `hh.area_type`; they should never
probe `ATYPE` or `area_class`.

Use `_materialize_preferred_column(...)` only when candidate selection needs
extra rules, such as rejecting numeric purpose codes. Use `overwrite=True` only
when prepare intentionally replaces an existing canonical column.

### 3. Add Cache Identity

Add the candidate list to the `columns` mapping returned by
`prepare_signature_payload()`:

```python
"area_type": list(config.col_area_type),
```

The summary signature currently incorporates the prepared column payload, so
this also invalidates affected summary caches.

### 4. Test Precedence And Materialization

```python
def test_area_type_alias_materializes_canonical_column(tmp_path):
    config = _write_config(
        tmp_path,
        column_lines=["area_type: [area_class, ATYPE]"],
    )
    raw = _raw_run()
    raw.hh = raw.hh.with_columns(
        pl.Series("area_class", ["urban"]),
        pl.Series("ATYPE", [99]),
    )

    prepared = prepare_data(raw, config)

    assert prepared.hh["area_type"].to_list() == ["urban"]
    assert config.prepare_signature_payload()["columns"]["area_type"] == [
        "area_class",
        "ATYPE",
    ]
```

Also test the default candidate list and missing-source behavior.

## Worked Example: Add A Label Mapping And Use It On A Page

Label mappings are presentation data. They do not change raw values used for
filtering or summary grouping.

Suppose a summary contains `employment_status` values `0`, `1`, and `2`:

```yaml
display:
  labels:
    employment_status:
      mapping:
        "0": Not employed
        "1": Part time
        "2": Full time
      order: data
```

New category IDs do not require a schema change. `normalize_categories()` loads
arbitrary category IDs into `config.dashboard_labels`.

### Selector With Display-To-Raw Mapping

Use `column_options()` from `dashboard.helpers.category_helpers`:

```python
def employment_status_options(self):
    data = self.data.summary("workers_by_employment_status")
    if not data:
        return ["All"]
    options, self._employment_status_by_label = column_options(
        data.to_list(),
        "employment_status",
        category_id="employment_status",
        config=self.config,
        total_raw=None,
        total_label="All",
    )
    return options


def selected_employment_status_raw(self):
    return self._employment_status_by_label.get(self.employment_status.value)
```

The widget shows `Full time`; the data filter still uses raw value `2`. This
avoids corrupting joins, selector state, or summary contracts with display
text.

### Add A Label Column For A Figure

Use `label_category_data()` when a plot needs a labeled column:

```python
labeled = label_category_data(
    data.to_list(),
    source_col="employment_status",
    category_id="employment_status",
    config=self.config,
    target_col="employment_status_label",
)
return self.plot.bar(
    labeled,
    x="employment_status_label",
    y="person_count",
    category_order=self.config.ordered_labels(
        "employment_status", ["0", "1", "2"]
    ),
)
```

If many pages use the category, keep mapping mechanics in
`dashboard/helpers/category_helpers.py`. If the mapping changes canonical
summary values rather than appearance, it belongs under
`summarize.category_normalization` and must be applied by the owning summary
logic.

### Test Raw And Display Behavior Separately

```python
assert config.label_value("employment_status", "2") == "Full time"
assert config.ordered_values(
    "employment_status", ["2", "0", "1"]
) == ["0", "1", "2"]
```

Add a page/helper test proving that selection of `Full time` filters raw `2`.
This catches the most common label-wiring regression.

## Completion Checklist

- Unknown keys and wrong types fail near the config boundary.
- Raw YAML is normalized once and represented by a typed `Config` field.
- The setting belongs to exactly the cache signatures it can affect.
- Prepared code emits canonical names; summaries do not probe source aliases.
- Dashboard filtering retains raw values and labels only at presentation time.
- `config.yaml`, chapter 13, and focused tests are updated together.

## Related Chapters

- [13 - Configuration Reference](13-configuration-reference.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [32 - Figures And Widgets](32-figures-and-widgets.md)
- [41 - Data Extension Cookbook](41-data-extension-cookbook.md)
- [43 - Weighting And Hosting Extensions](43-weighting-hosting-extensions.md)
