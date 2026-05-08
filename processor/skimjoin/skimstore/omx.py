from __future__ import annotations

from pathlib import Path

import openmatrix as omx

from processor.skimjoin.skimstore.base import SkimStore


class OmxSkimStore(SkimStore):
    def __init__(self) -> None:
        super().__init__()
        self._zone_maps: dict[tuple[str, str], dict[int, int] | None] = {}

    def get_zone_map(
        self,
        file_path: str,
        *,
        lookup_name: str | None = None,
    ) -> dict[int, int] | None:
        if not lookup_name:
            return None
        key = (file_path, lookup_name)
        if key in self._zone_maps:
            return self._zone_maps[key]

        handle = omx.open_file(str(Path(file_path)))
        try:
            available = set(handle.list_mappings())
            if lookup_name not in available:
                raise ValueError(
                    f"OMX lookup {lookup_name!r} was not found in {file_path}."
                )
            raw_map = handle.mapping(lookup_name)
        finally:
            handle.close()

        normalized: dict[int, int] = {}
        for raw_key, raw_value in raw_map.items():
            key_value = (
                raw_key.decode("utf-8")
                if isinstance(raw_key, (bytes, bytearray))
                else raw_key
            )
            try:
                normalized[int(key_value)] = int(raw_value)
            except Exception:
                continue
        self._zone_maps[key] = normalized or None
        return self._zone_maps[key]


__all__ = ["OmxSkimStore", "SkimStore"]
