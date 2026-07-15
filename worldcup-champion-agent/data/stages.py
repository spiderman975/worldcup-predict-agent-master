from __future__ import annotations

from typing import Final


GROUP: Final = 1
ROUND_OF_32: Final = 2
ROUND_OF_16: Final = 3
QUARTER: Final = 4
SEMI: Final = 5
THIRD_PLACE: Final = 6
FINAL: Final = 7

STAGE_NUMBER_TO_KEY: Final[dict[int, str]] = {
    GROUP: "group",
    ROUND_OF_32: "round_of_32",
    ROUND_OF_16: "round_of_16",
    QUARTER: "quarter",
    SEMI: "semi",
    THIRD_PLACE: "third_place",
    FINAL: "final",
}

STAGE_KEY_TO_NUMBER: Final[dict[str, int]] = {value: key for key, value in STAGE_NUMBER_TO_KEY.items()}

FOOTBALL_DATA_STAGE_TO_NUMBER: Final[dict[str, int]] = {
    "GROUP_STAGE": GROUP,
    "GROUP": GROUP,
    "LAST_32": ROUND_OF_32,
    "ROUND_OF_32": ROUND_OF_32,
    "LAST_16": ROUND_OF_16,
    "ROUND_OF_16": ROUND_OF_16,
    "QUARTER_FINALS": QUARTER,
    "QUARTER": QUARTER,
    "SEMI_FINALS": SEMI,
    "SEMI": SEMI,
    "THIRD_PLACE": THIRD_PLACE,
    "FINAL": FINAL,
}


def football_data_stage_to_number(value: object) -> int:
    stage = str(value or "").strip().upper()
    if stage in FOOTBALL_DATA_STAGE_TO_NUMBER:
        return FOOTBALL_DATA_STAGE_TO_NUMBER[stage]
    raise ValueError(f"Unsupported football-data.org stage: {value!r}")


def stage_key_from_number(value: int) -> str:
    stage = int(value)
    if stage not in STAGE_NUMBER_TO_KEY:
        raise ValueError(f"Unsupported match stage number: {value!r}")
    return STAGE_NUMBER_TO_KEY[stage]


def validate_stage_number(value: int) -> int:
    stage = int(value)
    if stage not in STAGE_NUMBER_TO_KEY:
        raise ValueError(f"Match stage must be one of {sorted(STAGE_NUMBER_TO_KEY)}, got {value!r}")
    return stage


def stage_order(value: int | str) -> int:
    if isinstance(value, str):
        key = value.strip()
        if key not in STAGE_KEY_TO_NUMBER:
            raise ValueError(f"Unsupported match stage key: {value!r}")
        return STAGE_KEY_TO_NUMBER[key]
    return validate_stage_number(value)
