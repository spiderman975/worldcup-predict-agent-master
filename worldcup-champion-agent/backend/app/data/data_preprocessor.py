from typing import Any

import pandas as pd

from app.data.team_name_mapper import normalize_team_name


def normalize_features(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """统一名称并保留 0-1 特征区间，便于评分模块直接使用。"""

    if not teams:
        return []
    df = pd.DataFrame(teams).copy()
    df["name"] = df["name"].map(normalize_team_name)
    numeric_cols = [
        "attack_score",
        "defense_score",
        "recent_form",
        "worldcup_history_score",
        "squad_availability_score",
    ]
    for col in numeric_cols:
        df[col] = df[col].fillna(0.8).clip(0, 1)
    return df.to_dict(orient="records")
