from __future__ import annotations

import csv
import unicodedata
from pathlib import Path


DEFAULT_ALIAS_PATH = Path("datasets/team_aliases.csv")


def load_team_aliases(path: str | Path = DEFAULT_ALIAS_PATH) -> dict[str, str]:
    alias_path = Path(path)
    aliases: dict[str, str] = {}
    if not alias_path.exists():
        return aliases
    with alias_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source = (row.get("source_name") or "").strip()
            canonical = (row.get("canonical_name") or "").strip()
            if source and canonical:
                aliases[_alias_key(source)] = canonical
                aliases[_alias_key(canonical)] = canonical
    return aliases


def canonicalize_team_name(name: str, aliases: dict[str, str] | None = None) -> str:
    cleaned = " ".join(str(name or "").replace("\u2019", "'").split())
    if not cleaned:
        return ""
    alias_map = aliases or {}
    return alias_map.get(_alias_key(cleaned), cleaned)


def _alias_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.replace("\u2019", "'"))
    asciiish = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(asciiish.casefold().split())
