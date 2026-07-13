from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


def load_csv_rows(path: str | Path, required_fields: Iterable[str] | None = None) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file has no header row: {csv_path}")
        fields = {field.strip() for field in reader.fieldnames if field}
        missing = sorted(set(required_fields or []) - fields)
        if missing:
            raise ValueError(f"{csv_path} is missing required fields: {', '.join(missing)}")
        return [_clean_row(row) for row in reader]


def load_team_rows(path: str | Path) -> list[dict[str, str]]:
    return load_csv_rows(
        path,
        required_fields=[
            "name",
            "group",
            "attack_team",
            "defensive_team",
            "streak",
            "starting_lineup",
        ],
    )


def _clean_row(row: dict[str, str | None]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        cleaned[key.strip()] = "" if value is None else value.strip()
    return cleaned

