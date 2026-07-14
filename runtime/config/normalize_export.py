"""Export HTML and dashboard-page config normalization."""

from __future__ import annotations

from .common import normalize_optional_bool
from .models import (
    DashboardPageConfigEntry,
    ExportPageOverride,
    ExportPartOverride,
    ExportSelectorRequest,
)


def normalize_export_html_selection(
    raw_value,
    *,
    field_name: str,
    default: list[str],
    allowed: list[str],
) -> list[str]:
    if raw_value is None:
        raw_value = "default"

    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        if token == "default":
            result = list(default)
        elif token == "all":
            result = list(allowed)
        else:
            result = [token]
    elif isinstance(raw_value, list):
        result = []
        for item in raw_value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} entries must be strings.")
            token = item.strip().lower()
            if not token:
                continue
            result.append(token)
    else:
        raise ValueError(f"{field_name} must be 'default', 'all', or a list of strings.")

    deduped: list[str] = []
    invalid: list[str] = []
    for token in result:
        if token not in allowed:
            invalid.append(token)
            continue
        if token not in deduped:
            deduped.append(token)

    if invalid:
        raise ValueError(
            f"Unsupported {field_name} values: "
            + ", ".join(repr(token) for token in invalid)
        )
    if not deduped:
        raise ValueError(f"{field_name} resolved to no values.")
    return deduped


def normalize_export_selector_request(
    raw_value,
    *,
    field_name: str,
) -> ExportSelectorRequest:
    if raw_value is None:
        return ExportSelectorRequest()

    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        if not token or token == "default":
            return ExportSelectorRequest(mode="default")
        if token == "all":
            return ExportSelectorRequest(mode="all")
        return ExportSelectorRequest(mode="explicit", values=(token,))

    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be 'default', 'all', or a list of strings.")

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip().lower()
        if not token:
            continue
        if token not in normalized:
            normalized.append(token)
    if not normalized:
        raise ValueError(f"{field_name} resolved to no values.")
    return ExportSelectorRequest(mode="explicit", values=tuple(normalized))


def normalize_excluded_ids(
    raw_value,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list of ids when provided.")
    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip().lower()
        if token and token not in normalized:
            normalized.append(token)
    return tuple(normalized)


def normalize_export_page_override(
    raw_value,
    *,
    field_name: str,
) -> ExportPageOverride:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    enabled = normalize_optional_bool(
        raw_value.get("enabled"), field_name=f"{field_name}.enabled"
    )

    selector_requests: dict[str, ExportSelectorRequest] = {}
    parts: dict[str, ExportPartOverride] = {}
    for raw_key, raw_item in raw_value.items():
        key = str(raw_key).strip().lower()
        if not key:
            raise ValueError(f"{field_name} contains an empty key.")
        if key == "enabled":
            continue
        if key == "parts":
            if not isinstance(raw_item, dict):
                raise ValueError(f"{field_name}.parts must be a mapping.")
            for raw_part_id, raw_part_cfg in raw_item.items():
                part_id = str(raw_part_id).strip().lower()
                if not part_id:
                    raise ValueError(f"{field_name}.parts contains an empty part id.")
                if not isinstance(raw_part_cfg, dict):
                    raise ValueError(f"{field_name}.parts.{part_id} must be a mapping.")
                if set(raw_part_cfg) - {"enabled"}:
                    invalid_keys = ", ".join(
                        repr(str(item))
                        for item in sorted(set(raw_part_cfg) - {"enabled"})
                    )
                    raise ValueError(
                        f"{field_name}.parts.{part_id} only supports 'enabled'. Invalid keys: {invalid_keys}"
                    )
                parts[part_id] = ExportPartOverride(
                    enabled=normalize_optional_bool(
                        raw_part_cfg.get("enabled"),
                        field_name=f"{field_name}.parts.{part_id}.enabled",
                    )
                )
            continue
        selector_requests[key] = normalize_export_selector_request(
            raw_item,
            field_name=f"{field_name}.{key}",
        )

    return ExportPageOverride(
        enabled=enabled,
        selector_requests=selector_requests,
        parts=parts,
    )


def normalize_dashboard_page_entries(
    raw_value,
    *,
    field_name: str,
) -> list[DashboardPageConfigEntry]:
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    entries: list[DashboardPageConfigEntry] = []
    seen_page_ids: set[str] = set()
    for raw_entry in raw_value:
        if isinstance(raw_entry, str):
            page_id = raw_entry.strip().lower()
            if not page_id:
                raise ValueError(f"{field_name} contains an empty page id.")
            if page_id in seen_page_ids:
                raise ValueError(f"{field_name} contains duplicate page id {page_id!r}.")
            entries.append(DashboardPageConfigEntry(page_id=page_id))
            seen_page_ids.add(page_id)
            continue

        if not isinstance(raw_entry, dict) or len(raw_entry) != 1:
            raise ValueError(f"{field_name} entries must be strings or single-key mappings.")
        raw_group_id, raw_children = next(iter(raw_entry.items()))
        page_id = str(raw_group_id).strip().lower()
        if not page_id:
            raise ValueError(f"{field_name} contains an empty page id.")
        if page_id in seen_page_ids:
            raise ValueError(f"{field_name} contains duplicate page id {page_id!r}.")

        if isinstance(raw_children, str):
            token = raw_children.strip().lower()
            if token not in {"default", "all"}:
                raise ValueError(
                    f"{field_name}.{page_id} must be 'default', 'all', or a list of page ids."
                )
            entries.append(DashboardPageConfigEntry(page_id=page_id, mode=token))
        elif isinstance(raw_children, list):
            child_page_ids: list[str] = []
            for raw_child_page_id in raw_children:
                if not isinstance(raw_child_page_id, str):
                    raise ValueError(f"{field_name}.{page_id} entries must be strings.")
                child_page_id = raw_child_page_id.strip().lower()
                if not child_page_id or child_page_id in child_page_ids:
                    continue
                child_page_ids.append(child_page_id)
            if not child_page_ids:
                raise ValueError(f"{field_name}.{page_id} resolved to no page ids.")
            entries.append(
                DashboardPageConfigEntry(
                    page_id=page_id,
                    mode="explicit",
                    page_ids=tuple(child_page_ids),
                )
            )
        else:
            raise ValueError(
                f"{field_name}.{page_id} must be 'default', 'all', or a list of page ids."
            )
        seen_page_ids.add(page_id)

    return entries


def normalize_export_page_entries(
    raw_value,
    *,
    field_name: str,
) -> dict[str, ExportPageOverride]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    normalized: dict[str, ExportPageOverride] = {}
    for raw_page_id, raw_page_cfg in raw_value.items():
        page_id = str(raw_page_id).strip().lower()
        if not page_id:
            raise ValueError(f"{field_name} contains an empty page id.")
        if not isinstance(raw_page_cfg, dict):
            raise ValueError(f"{field_name}.{page_id} must be a mapping.")

        # An empty mapping selects a page or group without overriding its
        # selectors. Preserve it so dashboard.export.pages can also define the
        # exported page set.
        if not raw_page_cfg:
            normalized[page_id] = ExportPageOverride()
            continue

        is_leaf_override = any(
            str(key).strip().lower() in {"enabled", "parts"}
            or not isinstance(value, dict)
            for key, value in raw_page_cfg.items()
        )
        if is_leaf_override:
            normalized[page_id] = normalize_export_page_override(
                raw_page_cfg,
                field_name=f"{field_name}.{page_id}",
            )
            continue

        child_entries = raw_page_cfg
        if set(raw_page_cfg) == {"children"}:
            raw_children = raw_page_cfg["children"]
            if not isinstance(raw_children, dict):
                raise ValueError(f"{field_name}.{page_id}.children must be a mapping.")
            child_entries = raw_children

        for raw_child_page_id, raw_child_cfg in child_entries.items():
            child_page_id = str(raw_child_page_id).strip().lower()
            if not child_page_id:
                raise ValueError(f"{field_name}.{page_id} contains an empty page id.")
            normalized[f"{page_id}.{child_page_id}"] = normalize_export_page_override(
                raw_child_cfg,
                field_name=f"{field_name}.{page_id}.children.{child_page_id}",
            )
    return normalized
