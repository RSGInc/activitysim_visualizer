"""Category, label, and student-type normalization."""

from __future__ import annotations

from typing import Any

from .common import normalize_column_aliases
from .models import CategorySpec, StudentTypeConfig, StudentTypePersonSelector

ESCORT_CANONICAL_DEFAULT_LABELS: dict[str, str] = {
    "not_escorted": "No Escort",
    "pure_escort": "Pure Escort",
    "ride_share": "Ride Share",
}


def escort_normalization_key(raw_value) -> str | None:
    if raw_value is None:
        return "not_escorted"
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return "not_escorted"
        lowered = stripped.lower()
        compact = lowered.replace("_", "").replace(" ", "")
        if lowered in {"none", "null", "nan"}:
            return "not_escorted"
        if compact in {"0", "notescorted", "noescort"}:
            return "not_escorted"
        if compact in {"1", "pureescort"}:
            return "pure_escort"
        if compact in {"2", "rideshare"}:
            return "ride_share"
        return None
    return escort_normalization_key(str(raw_value))


def normalize_escort_category_spec(spec: CategorySpec | None) -> CategorySpec:
    canonical_labels = dict(ESCORT_CANONICAL_DEFAULT_LABELS)
    extras: list[tuple[str, str]] = []
    seen_extras: set[str] = set()

    if spec is not None:
        for raw_key, display_label in spec.mapping_items:
            normalized = escort_normalization_key(raw_key)
            if normalized is not None:
                canonical_labels[normalized] = display_label
                continue
            if raw_key not in seen_extras:
                extras.append((raw_key, display_label))
                seen_extras.add(raw_key)
        for canonical in ESCORT_CANONICAL_DEFAULT_LABELS:
            for raw_key, display_label in spec.mapping_items:
                if raw_key == canonical:
                    canonical_labels[canonical] = display_label
                    break

    mapping_items = [
        (canonical, canonical_labels[canonical])
        for canonical in ("not_escorted", "pure_escort", "ride_share")
    ]
    if spec is not None:
        for raw_key, display_label in spec.mapping_items:
            if raw_key in {key for key, _ in mapping_items}:
                continue
            if raw_key not in seen_extras and escort_normalization_key(raw_key) is None:
                extras.append((raw_key, display_label))
                seen_extras.add(raw_key)
            elif (
                escort_normalization_key(raw_key) is not None
                and raw_key not in seen_extras
            ):
                extras.append((raw_key, display_label))
                seen_extras.add(raw_key)
    mapping_items.extend(extras)

    labels_by_raw = {raw_key: display_label for raw_key, display_label in mapping_items}
    return CategorySpec(
        mapping_items=tuple(mapping_items),
        labels_by_raw=labels_by_raw,
        raw_values_in_order=tuple(raw_key for raw_key, _ in mapping_items),
        fallback_order="data" if spec is None else spec.fallback_order,
    )


def normalize_category_order(raw_value, *, field_name: str) -> str:
    if raw_value is None:
        return "data"
    token = str(raw_value).strip().lower()
    if token not in {"ascending", "descending", "data"}:
        raise ValueError(
            f"{field_name} must be one of 'ascending', 'descending', or 'data'."
        )
    return token


def normalize_categories(
    raw_value,
    *,
    field_name: str,
) -> dict[str, CategorySpec]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    categories: dict[str, CategorySpec] = {}
    for raw_category_id, raw_spec in raw_value.items():
        category_id = str(raw_category_id).strip()
        if not category_id:
            raise ValueError(f"{field_name} contains an empty category id.")
        if not isinstance(raw_spec, dict):
            raise ValueError(f"{field_name}.{category_id} must be a mapping.")

        mapping_raw = raw_spec.get("mapping")
        if mapping_raw is None:
            mapping_items: list[tuple[str, str]] = []
        else:
            if not isinstance(mapping_raw, dict):
                raise ValueError(f"{field_name}.{category_id}.mapping must be a mapping.")
            mapping_items = [
                (str(raw_key), str(display_label))
                for raw_key, display_label in mapping_raw.items()
            ]
        spec = CategorySpec(
            mapping_items=tuple(mapping_items),
            labels_by_raw={
                raw_key: display_label for raw_key, display_label in mapping_items
            },
            raw_values_in_order=tuple(raw_key for raw_key, _ in mapping_items),
            fallback_order=normalize_category_order(
                raw_spec.get("order"),
                field_name=f"{field_name}.{category_id}.order",
            ),
        )
        categories[category_id] = spec
    return categories


def category_spec_from_mapping(
    mapping: dict[str, str] | None,
    *,
    fallback_order: str = "data",
) -> CategorySpec | None:
    if not mapping:
        return None
    mapping_items = [
        (str(raw_key), str(display_label)) for raw_key, display_label in mapping.items()
    ]
    return CategorySpec(
        mapping_items=tuple(mapping_items),
        labels_by_raw={
            raw_key: display_label for raw_key, display_label in mapping_items
        },
        raw_values_in_order=tuple(raw_key for raw_key, _ in mapping_items),
        fallback_order=fallback_order,
    )


def category_spec_from_sequence(
    values: list[str] | tuple[str, ...] | None,
) -> CategorySpec | None:
    if not values:
        return None
    normalized = tuple(str(value) for value in values)
    return CategorySpec(
        mapping_items=(),
        labels_by_raw={},
        raw_values_in_order=normalized,
        fallback_order="data",
    )


def category_specs_payload(
    categories: dict[str, CategorySpec],
) -> list[dict[str, Any]]:
    return [
        {
            "category_id": category_id,
            "mapping": [
                {"raw": raw_value, "label": display_label}
                for raw_value, display_label in spec.mapping_items
            ],
            "order": spec.fallback_order,
        }
        for category_id, spec in categories.items()
    ]


def student_type_defaults_to_university(
    label: str,
    land_use_columns: tuple[str, ...],
) -> bool:
    text = f"{label} {' '.join(land_use_columns)}".lower()
    return "univ" in text or "college" in text


def normalize_student_selector_values(
    raw_value,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(raw_value, (str, int, float, bool)):
        values = [raw_value]
    elif isinstance(raw_value, list):
        values = raw_value
    else:
        raise ValueError(f"{field_name} must be a scalar or list.")

    normalized: list[str] = []
    for value in values:
        token = str(value).strip()
        if not token or token in normalized:
            continue
        normalized.append(token)
    if not normalized:
        raise ValueError(f"{field_name} resolved to no values.")
    return tuple(normalized)


def normalize_student_types(
    raw_value,
    *,
    field_name: str,
) -> list[StudentTypeConfig]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    normalized: list[StudentTypeConfig] = []
    for idx, raw_entry in enumerate(raw_value):
        entry_name = f"{field_name}[{idx}]"
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{entry_name} must be a mapping.")

        label = str(raw_entry.get("label", "")).strip()
        if not label:
            raise ValueError(f"{entry_name}.label is required.")

        land_use_columns = normalize_column_aliases(
            raw_entry.get("land_use_columns"),
            field_name=f"{entry_name}.land_use_columns",
            default=[],
        )

        person_raw = raw_entry.get("person")
        person_selector: StudentTypePersonSelector | None = None
        if person_raw is not None:
            if not isinstance(person_raw, dict):
                raise ValueError(f"{entry_name}.person must be a mapping.")
            allowed_keys = {"is_university", "school_segment", "SCHG", "pstudent"}
            unknown_keys = sorted(set(person_raw) - allowed_keys)
            if unknown_keys:
                raise ValueError(
                    f"{entry_name}.person contains unsupported keys: "
                    + ", ".join(unknown_keys)
                )

            is_university = person_raw.get("is_university")
            if is_university is not None and not isinstance(is_university, bool):
                raise ValueError(f"{entry_name}.person.is_university must be true or false.")
            person_selector = StudentTypePersonSelector(
                is_university=is_university,
                school_segment=(
                    normalize_student_selector_values(
                        person_raw["school_segment"],
                        field_name=f"{entry_name}.person.school_segment",
                    )
                    if "school_segment" in person_raw
                    else ()
                ),
                SCHG=(
                    normalize_student_selector_values(
                        person_raw["SCHG"],
                        field_name=f"{entry_name}.person.SCHG",
                    )
                    if "SCHG" in person_raw
                    else ()
                ),
                pstudent=(
                    normalize_student_selector_values(
                        person_raw["pstudent"],
                        field_name=f"{entry_name}.person.pstudent",
                    )
                    if "pstudent" in person_raw
                    else ()
                ),
            )

        normalized.append(
            StudentTypeConfig(
                label=label,
                land_use_columns=tuple(land_use_columns),
                person=person_selector,
            )
        )

    if len(normalized) > 2:
        for idx, entry in enumerate(normalized):
            if entry.person is None and not student_type_defaults_to_university(
                entry.label, entry.land_use_columns
            ):
                raise ValueError(
                    f"{field_name}[{idx}].person is required for custom multi-school segmentation."
                )
    return normalized
