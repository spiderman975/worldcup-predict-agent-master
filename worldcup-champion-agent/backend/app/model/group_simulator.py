from collections import defaultdict
from typing import Any

from app.model.match_predictor import predict_match


def simulate_group_stage(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    ratings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """预测全部小组赛，并按积分、净胜球、进球数排序产生出线队。"""

    tables: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    predictions: list[dict[str, Any]] = []
    for team in teams:
        tables[team["group"]][team["team_id"]] = {
            "team_id": team["team_id"],
            "team_name": team["name"],
            "played": 0,
            "points": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "qualified": False,
            "rank": 0,
        }

    for match in matches:
        if match["stage"] != "group":
            continue
        prediction = predict_match(match, ratings, allow_draw=True)
        predictions.append(prediction)
        home_row = tables[match["group"]][match["home_team_id"]]
        away_row = tables[match["group"]][match["away_team_id"]]
        hs = prediction["predicted_home_score"]
        aw = prediction["predicted_away_score"]
        home_row["played"] += 1
        away_row["played"] += 1
        home_row["goals_for"] += hs
        home_row["goals_against"] += aw
        away_row["goals_for"] += aw
        away_row["goals_against"] += hs
        if hs > aw:
            home_row["points"] += 3
        elif aw > hs:
            away_row["points"] += 3
        else:
            home_row["points"] += 1
            away_row["points"] += 1

    group_tables: dict[str, list[dict[str, Any]]] = {}
    qualified: dict[str, list[str]] = {}
    third_place_rows: list[dict[str, Any]] = []
    for group, rows in tables.items():
        sorted_rows = sorted(
            rows.values(),
            key=lambda row: (
                row["points"],
                row["goals_for"] - row["goals_against"],
                row["goals_for"],
                ratings[row["team_id"]]["overall_rating"],
            ),
            reverse=True,
        )
        qualified[group] = []
        for rank, row in enumerate(sorted_rows, start=1):
            row["goal_difference"] = row["goals_for"] - row["goals_against"]
            row["rank"] = rank
            row["qualified"] = rank <= 2
            if row["qualified"]:
                qualified[group].append(row["team_id"])
            if rank == 3:
                third_place_rows.append({**row, "group": group})
        group_tables[group] = sorted_rows
    third_place_ranking = sorted(
        third_place_rows,
        key=lambda row: (row["points"], row["goal_difference"], row["goals_for"], ratings[row["team_id"]]["overall_rating"]),
        reverse=True,
    )
    for rank, row in enumerate(third_place_ranking, start=1):
        row["third_rank"] = rank
    return {
        "group_tables": group_tables,
        "group_stage_predictions": predictions,
        "qualified": qualified,
        "third_place_ranking": third_place_ranking,
    }
