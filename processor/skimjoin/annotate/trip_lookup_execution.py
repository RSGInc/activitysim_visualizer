from __future__ import annotations

from collections import Counter

import polars as pl

from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.inventory import qualified_matrix_reference
from processor.skimjoin.skimstore.base import SkimStore
from processor.skimjoin.annotate.trip_lookup_reports import _row_trip_id


def _inventory_metadata_frame(
    inventory: pl.DataFrame,
    normalized: NormalizedConfig,
) -> pl.DataFrame:
    selected = inventory.select(
        [
            "matrix_name",
            "file_path",
            "matrix_path",
            "source_kind",
            "key_column_name",
            "value_column_name",
            "origin_column_name",
            "destination_column_name",
        ]
    )
    inventory_rows = selected.to_dicts()
    name_counts = Counter(str(row["matrix_name"]) for row in inventory_rows)
    rows: list[dict[str, object]] = []
    ambiguous_sources: dict[str, list[str]] = {}
    for inventory_row in inventory_rows:
        row = dict(inventory_row)
        row["lookup_name"] = normalized.zone_mapping.resolve_lookup_name(
            str(row["file_path"])
        )
        row["ambiguous_sources"] = None
        qualified = dict(row)
        qualified["matrix_name"] = qualified_matrix_reference(
            str(row["file_path"]), str(row["matrix_name"])
        )
        rows.append(qualified)
        matrix_name = str(row["matrix_name"])
        if name_counts[matrix_name] == 1:
            rows.append(row)
        else:
            ambiguous_sources.setdefault(matrix_name, []).append(
                str(row["file_path"])
            )
    for matrix_name, file_paths in ambiguous_sources.items():
        rows.append(
            {
                "matrix_name": matrix_name,
                "file_path": None,
                "matrix_path": None,
                "source_kind": "ambiguous",
                "key_column_name": None,
                "value_column_name": None,
                "origin_column_name": None,
                "destination_column_name": None,
                "lookup_name": None,
                "ambiguous_sources": ", ".join(
                    sorted(
                        qualified_matrix_reference(file_path, matrix_name)
                        for file_path in file_paths
                    )
                ),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def _missing_matrix_frame(
    rule: NormalizedLookupRule,
    matrix_name: str,
    group: pl.DataFrame,
) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "_row_id": row.get("_row_id"),
                "rule_name": rule.name,
                "trip_id": _row_trip_id(row),
                "origin": row.get("lookup_origin"),
                "destination": row.get("lookup_destination"),
                "matrix_name": matrix_name,
                "reason": "missing_matrix",
            }
            for row in group.to_dicts()
        ],
        infer_schema_length=None,
    )


def _execute_lookup_batches(
    executable: pl.DataFrame,
    *,
    skim_store: SkimStore,
    normalized: NormalizedConfig,
) -> list[pl.DataFrame]:
    result_frames: list[pl.DataFrame] = []
    batch_columns = [
        "source_kind",
        "file_path",
        "matrix_path",
        "lookup_name",
        "key_column_name",
        "value_column_name",
        "origin_column_name",
        "destination_column_name",
    ]
    for _, batch in executable.group_by(batch_columns, maintain_order=True):
        result_frames.append(
            _execute_lookup_batch(batch, skim_store=skim_store, normalized=normalized)
        )
    return result_frames


def _execute_lookup_batch(
    batch: pl.DataFrame,
    *,
    skim_store: SkimStore,
    normalized: NormalizedConfig,
) -> pl.DataFrame:
    source_kind = str(batch.item(0, "source_kind"))
    file_path = str(batch.item(0, "file_path"))
    if source_kind == "keyed_column":
        results = skim_store.lookup_keyed_frame(
            file_path,
            batch,
            key_column_name=str(batch.item(0, "key_column_name")),
            value_column_name=str(batch.item(0, "value_column_name")),
        )
    elif source_kind == "od_table":
        results = skim_store.lookup_od_table_frame(
            file_path,
            batch,
            origin_column_name=str(batch.item(0, "origin_column_name")),
            destination_column_name=str(batch.item(0, "destination_column_name")),
            value_column_name=str(batch.item(0, "value_column_name")),
        )
    else:
        results = skim_store.lookup_values_frame(
            file_path,
            str(batch.item(0, "matrix_path")),
            batch,
            lookup_name=normalized.zone_mapping.resolve_lookup_name(file_path),
        )

    if "valid" not in results.columns:
        results = results.with_columns(pl.col("value").is_not_null().alias("valid"))
    return results.with_columns(pl.lit(False).alias("sentinel_hit"))
