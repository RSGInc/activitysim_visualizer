"""Prepared-run segmentation helpers."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from processor.analysis_units import (
    AnalysisUnit,
    SegmentMetadata,
    full_analysis_unit,
)
from processor.models import RunData
from runtime.config import (
    Config,
    CsvLookupSegmentationSource,
    PreparedColumnSegmentationSource,
    SegmentationDefinition,
)


@dataclass(frozen=True)
class ResolvedSegmentationSource:
    """Runtime-resolved source used to build segment membership."""

    source_type: str
    anchor_table: str
    anchor_key_column: str | None
    segment_value_column: str
    source_column: str | None = None
    csv_file: str | None = None
    csv_key_column: str | None = None


def _table_for(prepared_run: RunData, table_name: str) -> pl.DataFrame:
    table = getattr(prepared_run, table_name, None)
    if not isinstance(table, pl.DataFrame):
        raise ValueError(f"Prepared run does not include table {table_name!r}.")
    return table


def resolve_segmentation_source(
    *,
    prepared_run: RunData,
    seg_cfg,
) -> ResolvedSegmentationSource:
    """Resolve the configured segmentation source against one prepared run."""
    source = seg_cfg.source
    if source is None:
        raise ValueError("Segmentation is enabled but no source was configured.")

    if isinstance(source, PreparedColumnSegmentationSource):
        if source.source_table is not None:
            source_df = _table_for(prepared_run, source.source_table)
            if source.column not in source_df.columns:
                raise ValueError(
                    f"Configured segmentation column {source.column!r} was not found in prepared table {source.source_table!r}."
                )
            return ResolvedSegmentationSource(
                source_type=source.type,
                anchor_table=source.source_table,
                anchor_key_column=_anchor_key_for_table(source.source_table),
                segment_value_column=source.column,
                source_column=source.column,
            )

        matching_tables = [
            table_name
            for table_name in ("hh", "per", "tours", "trips", "land_use")
            if source.column in _table_for(prepared_run, table_name).columns
        ]
        if not matching_tables:
            raise ValueError(
                f"Configured segmentation column {source.column!r} was not found in hh, per, tours, trips, or land_use."
            )
        if len(matching_tables) > 1:
            raise ValueError(
                f"Configured segmentation column {source.column!r} appears in multiple prepared tables: {', '.join(matching_tables)}. Set segmentation.source.source_table."
            )
        table_name = matching_tables[0]
        anchor_key = _anchor_key_for_table(table_name)
        if table_name == "land_use":
            land_use_df = _table_for(prepared_run, "land_use")
            if "MAZ" in land_use_df.columns:
                anchor_key = "MAZ"
            elif "TAZ" in land_use_df.columns:
                anchor_key = "TAZ"
        return ResolvedSegmentationSource(
            source_type=source.type,
            anchor_table=table_name,
            anchor_key_column=anchor_key,
            segment_value_column=source.column,
            source_column=source.column,
        )

    if not isinstance(source, CsvLookupSegmentationSource):
        raise ValueError("Unsupported segmentation source configuration.")

    source_df = _table_for(prepared_run, source.join_source_table)
    if source.join_source_key_column not in source_df.columns:
        raise ValueError(
            f"Prepared table {source.join_source_table!r} is missing configured segmentation join key {source.join_source_key_column!r}."
        )
    return ResolvedSegmentationSource(
        source_type=source.type,
        anchor_table=source.join_source_table,
        anchor_key_column=source.join_source_key_column,
        segment_value_column=source.segment_value_column,
        csv_file=source.file,
        csv_key_column=source.csv_key_column,
    )


def _anchor_key_for_table(table_name: str) -> str | None:
    mapping = {
        "hh": "household_id",
        "per": "person_id",
        "tours": "tour_id",
        "trips": "trip_id",
    }
    return mapping.get(table_name)


def build_segment_anchor_table(
    *,
    prepared_run: RunData,
    seg_cfg,
    source: ResolvedSegmentationSource,
) -> pl.DataFrame:
    """Return the anchor table with a segment-value column available."""
    anchor_df = _table_for(prepared_run, source.anchor_table)
    if source.source_type == "prepared_column":
        return anchor_df

    cfg_source = seg_cfg.source
    if not isinstance(cfg_source, CsvLookupSegmentationSource):
        raise ValueError("CSV-backed segmentation source expected.")

    if anchor_df.is_empty():
        return anchor_df.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias(source.segment_value_column)
        )

    lookup = pl.DataFrame(
        {
            cfg_source.csv_key_column: [key for key, _ in cfg_source.lookup_rows],
            cfg_source.segment_value_column: [
                value for _, value in cfg_source.lookup_rows
            ],
        }
    )
    anchor_key_dtype = anchor_df.schema.get(cfg_source.join_source_key_column)
    lookup = lookup.with_columns(
        pl.col(cfg_source.csv_key_column).cast(anchor_key_dtype, strict=False)
    )
    joined = anchor_df.join(
        lookup,
        left_on=cfg_source.join_source_key_column,
        right_on=cfg_source.csv_key_column,
        how="left",
    )
    if joined.height != anchor_df.height:
        raise ValueError(
            f"Segmentation CSV join duplicated rows in anchor table {source.anchor_table!r}. Only one-to-one joins are supported."
        )
    return joined


def _slice_run_data_from_source_subset(
    *,
    prepared_run: RunData,
    source_table: str,
    matched_source_df: pl.DataFrame,
) -> RunData:
    if source_table == "hh":
        household_ids = matched_source_df.select("household_id").drop_nulls()
        hh = prepared_run.hh.join(household_ids, on="household_id", how="inner")
        per = prepared_run.per.join(household_ids, on="household_id", how="inner")
        tours = prepared_run.tours.join(household_ids, on="household_id", how="inner")
        trips = prepared_run.trips.join(household_ids, on="household_id", how="inner")
        tour_ids = tours.select("tour_id") if "tour_id" in tours.columns else pl.DataFrame()
        joint = (
            prepared_run.joint_participants.join(tour_ids, on="tour_id", how="inner")
            if not tour_ids.is_empty() and "tour_id" in prepared_run.joint_participants.columns
            else prepared_run.joint_participants.head(0)
        )
        return _copy_run_data(
            prepared_run,
            hh=hh,
            per=per,
            tours=tours,
            trips=trips,
            joint_participants=joint,
        )

    if source_table == "per":
        person_ids = matched_source_df.select("person_id").drop_nulls()
        per = prepared_run.per.join(person_ids, on="person_id", how="inner")
        household_ids = per.select("household_id").drop_nulls()
        hh = prepared_run.hh.join(household_ids, on="household_id", how="inner")
        tours = prepared_run.tours.join(person_ids, on="person_id", how="inner")
        trips = prepared_run.trips.join(person_ids, on="person_id", how="inner")
        joint = (
            prepared_run.joint_participants.join(person_ids, on="person_id", how="inner")
            if "person_id" in prepared_run.joint_participants.columns
            else prepared_run.joint_participants.head(0)
        )
        return _copy_run_data(
            prepared_run,
            hh=hh,
            per=per,
            tours=tours,
            trips=trips,
            joint_participants=joint,
        )

    if source_table == "tours":
        tour_ids = matched_source_df.select("tour_id").drop_nulls()
        tours = prepared_run.tours.join(tour_ids, on="tour_id", how="inner")
        person_ids = tours.select("person_id").drop_nulls()
        household_ids = tours.select("household_id").drop_nulls()
        per = prepared_run.per.join(person_ids, on="person_id", how="inner")
        hh = prepared_run.hh.join(household_ids, on="household_id", how="inner")
        trips = prepared_run.trips.join(tour_ids, on="tour_id", how="inner")
        joint = (
            prepared_run.joint_participants.join(tour_ids, on="tour_id", how="inner")
            if "tour_id" in prepared_run.joint_participants.columns
            else prepared_run.joint_participants.head(0)
        )
        return _copy_run_data(
            prepared_run,
            hh=hh,
            per=per,
            tours=tours,
            trips=trips,
            joint_participants=joint,
        )

    if source_table == "trips":
        trip_ids = matched_source_df.select("trip_id").drop_nulls()
        trips = prepared_run.trips.join(trip_ids, on="trip_id", how="inner")
        tour_ids = trips.select("tour_id").drop_nulls()
        person_ids = trips.select("person_id").drop_nulls()
        household_ids = trips.select("household_id").drop_nulls()
        tours = prepared_run.tours.join(tour_ids, on="tour_id", how="inner")
        per = prepared_run.per.join(person_ids, on="person_id", how="inner")
        hh = prepared_run.hh.join(household_ids, on="household_id", how="inner")
        joint = (
            prepared_run.joint_participants.join(tour_ids, on="tour_id", how="inner")
            if "tour_id" in prepared_run.joint_participants.columns
            else prepared_run.joint_participants.head(0)
        )
        return _copy_run_data(
            prepared_run,
            hh=hh,
            per=per,
            tours=tours,
            trips=trips,
            joint_participants=joint,
        )

    if source_table == "land_use":
        zone_key = next(
            (
                column
                for column in ("MAZ", "TAZ")
                if column in matched_source_df.columns
            ),
            None,
        )
        if zone_key is None:
            raise ValueError(
                "land_use segmentation requires a resolved MAZ or TAZ key column."
            )
        household_zone_col = "home_zone_id" if zone_key == "MAZ" else "home_taz"
        if household_zone_col not in prepared_run.hh.columns:
            raise ValueError(
                f"land_use segmentation could not find required household zone column {household_zone_col!r}."
            )
        zone_ids = matched_source_df.select(pl.col(zone_key).alias(household_zone_col)).drop_nulls()
        hh = prepared_run.hh.join(zone_ids, on=household_zone_col, how="inner")
        household_ids = hh.select("household_id").drop_nulls()
        per = prepared_run.per.join(household_ids, on="household_id", how="inner")
        tours = prepared_run.tours.join(household_ids, on="household_id", how="inner")
        trips = prepared_run.trips.join(household_ids, on="household_id", how="inner")
        tour_ids = tours.select("tour_id") if "tour_id" in tours.columns else pl.DataFrame()
        joint = (
            prepared_run.joint_participants.join(tour_ids, on="tour_id", how="inner")
            if not tour_ids.is_empty() and "tour_id" in prepared_run.joint_participants.columns
            else prepared_run.joint_participants.head(0)
        )
        land_use = prepared_run.land_use.join(
            matched_source_df.select(zone_key).drop_nulls(),
            on=zone_key,
            how="inner",
        )
        return RunData(
            label=prepared_run.label,
            run_dir=prepared_run.run_dir,
            skim_file=prepared_run.skim_file,
            hh=hh,
            per=per,
            tours=tours,
            trips=trips,
            joint_participants=joint,
            land_use=land_use,
            skim_matrix=prepared_run.skim_matrix,
            skim_zone_map=prepared_run.skim_zone_map,
            hh_weight_col=prepared_run.hh_weight_col,
            person_weight_col=prepared_run.person_weight_col,
            trip_weight_col=prepared_run.trip_weight_col,
            table_availability_metadata=prepared_run.table_availability_metadata,
            skimjoin_artifacts=prepared_run.skimjoin_artifacts,
            skimjoin_manifest=prepared_run.skimjoin_manifest,
            skimjoin_reports=prepared_run.skimjoin_reports,
        )

    raise ValueError(f"Unsupported segmentation source table {source_table!r}.")


def _copy_run_data(
    prepared_run: RunData,
    *,
    hh: pl.DataFrame,
    per: pl.DataFrame,
    tours: pl.DataFrame,
    trips: pl.DataFrame,
    joint_participants: pl.DataFrame,
) -> RunData:
    return RunData(
        label=prepared_run.label,
        run_dir=prepared_run.run_dir,
        skim_file=prepared_run.skim_file,
        hh=hh,
        per=per,
        tours=tours,
        trips=trips,
        joint_participants=joint_participants,
        land_use=prepared_run.land_use,
        skim_matrix=prepared_run.skim_matrix,
        skim_zone_map=prepared_run.skim_zone_map,
        hh_weight_col=prepared_run.hh_weight_col,
        person_weight_col=prepared_run.person_weight_col,
        trip_weight_col=prepared_run.trip_weight_col,
        table_availability_metadata=prepared_run.table_availability_metadata,
        skimjoin_artifacts=prepared_run.skimjoin_artifacts,
        skimjoin_manifest=prepared_run.skimjoin_manifest,
        skimjoin_reports=prepared_run.skimjoin_reports,
    )


def build_analysis_units_for_run(
    *,
    run_key: str,
    run_name: str,
    prepared_run: RunData,
    config: Config,
) -> list[AnalysisUnit]:
    """Expand one prepared run into full and segmented units for every type."""
    segmentation_settings = config.segmentation
    if not segmentation_settings.enabled:
        return [
            full_analysis_unit(
                run_key=run_key,
                run_name=run_name,
                prepared_run=prepared_run,
                segmentation_type="full",
            )
        ]

    units: list[AnalysisUnit] = [
        full_analysis_unit(
            run_key=run_key,
            run_name=run_name,
            prepared_run=prepared_run,
            segmentation_type="full",
        )
    ]
    for definition in segmentation_settings.definitions:
        units.extend(
            _build_definition_analysis_units(
                run_key=run_key,
                run_name=run_name,
                prepared_run=prepared_run,
                definition=definition,
            )
        )

    return units


def _build_definition_analysis_units(
    *,
    run_key: str,
    run_name: str,
    prepared_run: RunData,
    definition: SegmentationDefinition,
) -> list[AnalysisUnit]:
    units: list[AnalysisUnit] = []
    source = resolve_segmentation_source(prepared_run=prepared_run, seg_cfg=definition)
    source_df = build_segment_anchor_table(
        prepared_run=prepared_run,
        seg_cfg=definition,
        source=source,
    )
    for segment in definition.segments:
        matched_source_df = source_df.filter(
            pl.col(source.segment_value_column).is_in(list(segment.values))
        )
        if matched_source_df.is_empty() and definition.on_empty_segment == "skip":
            continue
        if matched_source_df.is_empty() and definition.on_empty_segment == "error":
            raise ValueError(
                f"Segment {segment.id!r} in segmentation {definition.name!r} matched no rows in run {run_name!r}."
            )
        sliced_run = _slice_run_data_from_source_subset(
            prepared_run=prepared_run,
            source_table=source.anchor_table,
            matched_source_df=matched_source_df,
        )
        units.append(
            AnalysisUnit(
                run_id=run_key,
                run_name=run_name,
                run_key=run_key,
                segmentation_type=definition.name,
                segment_id=segment.id,
                segment_label=segment.label,
                is_full=False,
                segment_metadata=SegmentMetadata(
                    segmentation_type=definition.name,
                    segment_id=segment.id,
                    segment_label=segment.label,
                    is_full=False,
                    source_type=source.source_type,
                    column=source.segment_value_column,
                    values=segment.values,
                    source_table=source.anchor_table,
                    source_key_column=source.anchor_key_column,
                    csv_file=source.csv_file,
                    csv_key_column=source.csv_key_column,
                    csv_segment_value_column=source.segment_value_column,
                ),
                prepared_run=sliced_run,
            )
        )
    return units
