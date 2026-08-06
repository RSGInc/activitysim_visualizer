# 42 - Config, Columns, And Labels

This chapter follows one YAML value through validation, typed configuration,
cache identity, prepared data, and dashboard presentation.

## First Decide Which Boundary Owns The Setting

| Setting changes... | Put it under... | Signature impact |
|---|---|---|
| prepared rows or columns | `prepare` or `columns` | Prepare, and usually summary downstream |
| summary values or grouping | `summarize` | Summary |
| labels, ordering, colors, or page appearance | `display` or `dashboard` | Presentation |
| which workflow executes | `pipeline` | Runtime plan; include data effects in the owning signature too |

A new setting needs more than a field on `Config`. Add validation,
normalization, a typed field, cache-signature ownership, a consumer, an example,
and tests.

## Worked Example: Add A New Config Item

In this example, the dashboard requires a presentation-only control:

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

Downstream code reads `config.show_zero_categories`, not the raw YAML mapping.

### 3. Put It In The Correct Signature

This control changes only rendering. Add it to
`presentation_signature_payload()` in `runtime/config/signatures.py`:

```python
return {
    # existing presentation values...
    "show_zero_categories": config.show_zero_categories,
}
```

Do not add it to the prepare or summary signatures. If you add it, a display
change causes unnecessary cache rebuilds.

### 4. Consume It At The Presentation Boundary

For example, a shared category helper can add absent categories when the value
is true:

```python
if config.show_zero_categories:
    chart_data = complete_category_rows(chart_data, expected_categories)
```

Use a shared helper when several pages need the setting; keep page-specific
behavior on the page itself.

### 5. Document And Test It

Update `config.yaml` and chapter 13. Test the default, an explicit value, and an
incorrect type. Also test signature ownership and visible consumer behavior.

The examples below use module-local helpers named `_write_config()` and
`_raw_run()`. These helpers are not repository-wide pytest fixtures. Define a
small helper in the relevant test module, or use its existing configuration
and run factory. `extra_lines` and `column_lines` are example helper arguments.
They are not public configuration APIs.

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

In this example, models use `area_type`, `ATYPE`, or `area_class` for household
area type. The prepared contract must supply one stable name:
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

The loader gets `CANONICAL_COLUMN_KEYS` from this mapping, so
`columns.area_type` becomes valid automatically. Add the typed field to
`Config`:

```python
col_area_type: list[str]
```

The user can now change the order of preference:

```yaml
columns:
  area_type: [area_class, ATYPE]
```

The loader uses the first available candidate.

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

Keep configured source candidates in the configuration. Keep the stable output
name in prepare. Summary builders must require `hh.area_type`. They must not
search for `ATYPE` or `area_class`.

Use `_materialize_preferred_column(...)` only when candidate selection requires
more rules. One example is the rejection of numeric purpose codes. Use
`overwrite=True` only when prepare must replace an existing canonical column.

### 3. Add Cache Identity

Add the candidate list to the `columns` mapping returned by
`prepare_signature_payload()`:

```python
"area_type": list(config.col_area_type),
```

The summary signature includes the prepared column payload, so this change also
invalidates the affected summary caches.

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

Label mappings are presentation data. They do not change raw values for filters
or summary groups.

In this example, a summary contains `employment_status` values `0`, `1`, and `2`:

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
all category IDs into `config.dashboard_labels`.

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

The widget shows `Full time`, while the data filter continues to use raw value
`2`. Display text therefore does not change joins, selector state, or summary
contracts.

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

If many pages use the category, put mapping logic in
`dashboard/helpers/category_helpers.py`. If the mapping changes canonical
summary values, put it under `summarize.category_normalization`. The relevant
summary logic must apply it.

### Test Raw And Display Behavior Separately

```python
assert config.label_value("employment_status", "2") == "Full time"
assert config.ordered_values(
    "employment_status", ["2", "0", "1"]
) == ["0", "1", "2"]
```

Add a page or helper test. Verify that a `Full time` selection filters raw value
`2`. This test identifies a common label connection error.

## Completion Checklist

- Unknown keys and wrong types fail near the config boundary.
- Normalize raw YAML one time and represent it with a typed `Config` field.
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
