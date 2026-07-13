import json
from itertools import combinations
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RAW_DIR = PROJECT_ROOT / "data" / "raw"


DEMO_TEAMS: list[dict[str, Any]] = [
    {"team_id": "BRA", "name": "Brazil", "group": "A", "fifa_rank": 5, "elo_rating": 2100, "attack_score": 0.92, "defense_score": 0.86, "recent_form": 0.84, "worldcup_history_score": 0.95, "squad_availability_score": 0.88},
    {"team_id": "MEX", "name": "Mexico", "group": "A", "fifa_rank": 14, "elo_rating": 1850, "attack_score": 0.74, "defense_score": 0.72, "recent_form": 0.70, "worldcup_history_score": 0.70, "squad_availability_score": 0.82},
    {"team_id": "CRO", "name": "Croatia", "group": "A", "fifa_rank": 10, "elo_rating": 1910, "attack_score": 0.78, "defense_score": 0.80, "recent_form": 0.76, "worldcup_history_score": 0.82, "squad_availability_score": 0.84},
    {"team_id": "JPN", "name": "Japan", "group": "A", "fifa_rank": 18, "elo_rating": 1810, "attack_score": 0.72, "defense_score": 0.70, "recent_form": 0.78, "worldcup_history_score": 0.58, "squad_availability_score": 0.86},
    {"team_id": "ARG", "name": "Argentina", "group": "B", "fifa_rank": 1, "elo_rating": 2140, "attack_score": 0.90, "defense_score": 0.88, "recent_form": 0.90, "worldcup_history_score": 0.96, "squad_availability_score": 0.90},
    {"team_id": "USA", "name": "USA", "group": "B", "fifa_rank": 13, "elo_rating": 1845, "attack_score": 0.73, "defense_score": 0.71, "recent_form": 0.74, "worldcup_history_score": 0.60, "squad_availability_score": 0.86},
    {"team_id": "BEL", "name": "Belgium", "group": "B", "fifa_rank": 8, "elo_rating": 1945, "attack_score": 0.83, "defense_score": 0.76, "recent_form": 0.73, "worldcup_history_score": 0.76, "squad_availability_score": 0.82},
    {"team_id": "KOR", "name": "South Korea", "group": "B", "fifa_rank": 23, "elo_rating": 1760, "attack_score": 0.68, "defense_score": 0.67, "recent_form": 0.72, "worldcup_history_score": 0.55, "squad_availability_score": 0.84},
    {"team_id": "FRA", "name": "France", "group": "C", "fifa_rank": 2, "elo_rating": 2130, "attack_score": 0.93, "defense_score": 0.87, "recent_form": 0.86, "worldcup_history_score": 0.93, "squad_availability_score": 0.87},
    {"team_id": "GER", "name": "Germany", "group": "C", "fifa_rank": 12, "elo_rating": 1950, "attack_score": 0.84, "defense_score": 0.78, "recent_form": 0.70, "worldcup_history_score": 0.94, "squad_availability_score": 0.83},
    {"team_id": "URU", "name": "Uruguay", "group": "C", "fifa_rank": 11, "elo_rating": 1890, "attack_score": 0.77, "defense_score": 0.79, "recent_form": 0.75, "worldcup_history_score": 0.81, "squad_availability_score": 0.82},
    {"team_id": "MAR", "name": "Morocco", "group": "C", "fifa_rank": 16, "elo_rating": 1835, "attack_score": 0.70, "defense_score": 0.82, "recent_form": 0.79, "worldcup_history_score": 0.62, "squad_availability_score": 0.85},
    {"team_id": "ENG", "name": "England", "group": "D", "fifa_rank": 4, "elo_rating": 2070, "attack_score": 0.88, "defense_score": 0.84, "recent_form": 0.83, "worldcup_history_score": 0.86, "squad_availability_score": 0.86},
    {"team_id": "ESP", "name": "Spain", "group": "D", "fifa_rank": 3, "elo_rating": 2085, "attack_score": 0.87, "defense_score": 0.85, "recent_form": 0.82, "worldcup_history_score": 0.84, "squad_availability_score": 0.88},
    {"team_id": "POR", "name": "Portugal", "group": "D", "fifa_rank": 6, "elo_rating": 2030, "attack_score": 0.89, "defense_score": 0.81, "recent_form": 0.80, "worldcup_history_score": 0.78, "squad_availability_score": 0.85},
    {"team_id": "NED", "name": "Netherlands", "group": "D", "fifa_rank": 7, "elo_rating": 2020, "attack_score": 0.85, "defense_score": 0.83, "recent_form": 0.81, "worldcup_history_score": 0.83, "squad_availability_score": 0.84},
]


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_demo_matches(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 4 个小组生成单循环赛程，每组 6 场、总计 24 场。"""

    matches: list[dict[str, Any]] = []
    for group in sorted({team["group"] for team in teams}):
        group_teams = [team for team in teams if team["group"] == group]
        for index, (home, away) in enumerate(combinations(group_teams, 2), start=1):
            matches.append(
                {
                    "match_id": f"{group}{index}",
                    "stage": "group",
                    "group": group,
                    "home_team_id": home["team_id"],
                    "away_team_id": away["team_id"],
                    "match_time": f"2026-06-{11 + len(matches):02d}T20:00:00",
                    "venue": "Demo Stadium",
                }
            )
    return matches


def ensure_demo_data() -> None:
    """如果本地数据不存在，自动生成完整 demo 数据，保证项目开箱可跑。"""

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    teams_path = PROCESSED_DIR / "teams.json"
    matches_path = PROCESSED_DIR / "matches_2026.json"
    features_path = PROCESSED_DIR / "team_features.json"
    if not teams_path.exists():
        _write_json(teams_path, DEMO_TEAMS)
    if not matches_path.exists():
        _write_json(matches_path, _build_demo_matches(DEMO_TEAMS))
    if not features_path.exists():
        _write_json(features_path, {team["team_id"]: team for team in DEMO_TEAMS})
    for raw_name in ["historical_matches.csv", "worldcup_history.csv", "fifa_rankings.csv"]:
        raw_path = RAW_DIR / raw_name
        if not raw_path.exists():
            raw_path.write_text("source,description\nlocal_demo,placeholder for future ingestion\n", encoding="utf-8")


def load_processed_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """加载球队、赛程和特征数据；缺失时先生成 demo 数据。"""

    ensure_demo_data()
    teams = json.loads((PROCESSED_DIR / "teams.json").read_text(encoding="utf-8"))
    matches = json.loads((PROCESSED_DIR / "matches_2026.json").read_text(encoding="utf-8"))
    features = json.loads((PROCESSED_DIR / "team_features.json").read_text(encoding="utf-8"))
    return teams, matches, features
