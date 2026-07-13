from collections import Counter, defaultdict
from typing import Any

import numpy as np

from app.model.group_simulator import simulate_group_stage
from app.model.match_predictor import predict_match


def build_knockout_matches(qualified: dict[str, list[str]]) -> list[dict[str, Any]]:
    """按 demo 规则生成 8 强：A1-B2、B1-A2、C1-D2、D1-C2。"""

    pairings = [("A", 0, "B", 1), ("B", 0, "A", 1), ("C", 0, "D", 1), ("D", 0, "C", 1)]
    return [
        {
            "match_id": f"QF{index}",
            "stage": "quarter",
            "group": None,
            "home_team_id": qualified[g1][i1],
            "away_team_id": qualified[g2][i2],
            "match_time": f"2026-07-{index:02d}T20:00:00",
            "venue": "Demo Knockout Stadium",
        }
        for index, (g1, i1, g2, i2) in enumerate(pairings, start=1)
    ]


def predict_knockout(qualified: dict[str, list[str]], ratings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """使用确定性单场预测生成淘汰赛路径。"""

    quarters = build_knockout_matches(qualified)
    quarter_predictions = [predict_match(match, ratings, allow_draw=False) for match in quarters]
    semis = [
        {**quarters[0], "match_id": "SF1", "stage": "semi", "home_team_id": quarter_predictions[0]["winner"], "away_team_id": quarter_predictions[1]["winner"]},
        {**quarters[2], "match_id": "SF2", "stage": "semi", "home_team_id": quarter_predictions[2]["winner"], "away_team_id": quarter_predictions[3]["winner"]},
    ]
    semi_predictions = [predict_match(match, ratings, allow_draw=False) for match in semis]
    final = {
        **semis[0],
        "match_id": "F1",
        "stage": "final",
        "home_team_id": semi_predictions[0]["winner"],
        "away_team_id": semi_predictions[1]["winner"],
    }
    final_prediction = predict_match(final, ratings, allow_draw=False)
    return {
        "quarter": quarter_predictions,
        "semi": semi_predictions,
        "final": [final_prediction],
        "champion": final_prediction["winner"],
    }


def predict_knockout_until_round(
    qualified: dict[str, list[str]],
    ratings: dict[str, dict[str, Any]],
    target_round: str = "final",
) -> dict[str, Any]:
    """按目标阶段逐步生成淘汰赛预测，支持 API 单独触发某一阶段。"""

    knockout = predict_knockout(qualified, ratings)
    if target_round == "quarter":
        return {"quarter": knockout["quarter"], "champion": None}
    if target_round == "semi":
        return {"quarter": knockout["quarter"], "semi": knockout["semi"], "champion": None}
    return knockout


def _sample_group_stage(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    ratings: dict[str, dict[str, Any]],
    rng: np.random.Generator,
) -> dict[str, list[str]]:
    tables: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for team in teams:
        tables[team["group"]][team["team_id"]] = {"points": 0, "gf": 0, "ga": 0}
    for match in matches:
        prediction = predict_match(match, ratings, allow_draw=True)
        probs = np.array(prediction["score_matrix"]).flatten()
        index = int(rng.choice(len(probs), p=probs / probs.sum()))
        hs, aw = divmod(index, 6)
        home = tables[match["group"]][match["home_team_id"]]
        away = tables[match["group"]][match["away_team_id"]]
        home["gf"] += hs
        home["ga"] += aw
        away["gf"] += aw
        away["ga"] += hs
        if hs > aw:
            home["points"] += 3
        elif aw > hs:
            away["points"] += 3
        else:
            home["points"] += 1
            away["points"] += 1
    qualified: dict[str, list[str]] = {}
    for group, rows in tables.items():
        sorted_rows = sorted(
            rows.items(),
            key=lambda item: (item[1]["points"], item[1]["gf"] - item[1]["ga"], item[1]["gf"], ratings[item[0]]["overall_rating"]),
            reverse=True,
        )
        qualified[group] = [team_id for team_id, _ in sorted_rows[:2]]
    return qualified


def _sample_knockout_winner(match: dict[str, Any], ratings: dict[str, dict[str, Any]], rng: np.random.Generator) -> str:
    prediction = predict_match(match, ratings, allow_draw=False)
    home_prob = prediction["home_win_prob"] + prediction["draw_prob"] * ratings[match["home_team_id"]]["overall_rating"] / (
        ratings[match["home_team_id"]]["overall_rating"] + ratings[match["away_team_id"]]["overall_rating"]
    )
    return match["home_team_id"] if rng.random() < home_prob else match["away_team_id"]


def simulate_tournament(
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    ratings: dict[str, dict[str, Any]],
    runs: int = 1000,
) -> dict[str, Any]:
    """运行确定性淘汰赛预测和 Monte Carlo 冠军概率模拟。"""

    group_result = simulate_group_stage(teams, matches, ratings)
    knockout = predict_knockout(group_result["qualified"], ratings)
    champion_counter: Counter[str] = Counter()
    reach_counter: dict[str, Counter[str]] = defaultdict(Counter)
    rng = np.random.default_rng(2026)

    for _ in range(runs):
        qualified = _sample_group_stage(teams, matches, ratings, rng)
        for group_teams in qualified.values():
            for team_id in group_teams:
                reach_counter[team_id]["quarter"] += 1
        qf_matches = build_knockout_matches(qualified)
        qf_winners = [_sample_knockout_winner(match, ratings, rng) for match in qf_matches]
        for team_id in qf_winners:
            reach_counter[team_id]["semi"] += 1
        sf_matches = [
            {**qf_matches[0], "home_team_id": qf_winners[0], "away_team_id": qf_winners[1]},
            {**qf_matches[2], "home_team_id": qf_winners[2], "away_team_id": qf_winners[3]},
        ]
        sf_winners = [_sample_knockout_winner(match, ratings, rng) for match in sf_matches]
        for team_id in sf_winners:
            reach_counter[team_id]["final"] += 1
        final_match = {**sf_matches[0], "home_team_id": sf_winners[0], "away_team_id": sf_winners[1]}
        champion = _sample_knockout_winner(final_match, ratings, rng)
        champion_counter[champion] += 1
        reach_counter[champion]["champion"] += 1

    champion_probabilities = [
        {"team_id": team_id, "team_name": ratings[team_id]["name"], "probability": round(count / runs, 4)}
        for team_id, count in champion_counter.most_common()
    ]
    round_reach_probabilities = {
        team_id: {round_name: round(count / runs, 4) for round_name, count in counter.items()}
        for team_id, counter in reach_counter.items()
    }
    return {
        "group_results": group_result,
        "knockout_results": knockout,
        "champion_probabilities": champion_probabilities,
        "round_reach_probabilities": round_reach_probabilities,
        "final_champion": champion_probabilities[0]["team_id"] if champion_probabilities else knockout["champion"],
        "most_likely_path": knockout,
    }
