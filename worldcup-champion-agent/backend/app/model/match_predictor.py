from typing import Any
import math

import numpy as np


def _team_name(team_id: str, ratings: dict[str, dict[str, Any]]) -> str:
    return ratings[team_id]["name"]


def _poisson_pmf(goals: int, expected_goals: float) -> float:
    """用标准库计算 Poisson 概率，减少运行环境对 scipy 的硬依赖。"""

    return math.exp(-expected_goals) * expected_goals**goals / math.factorial(goals)


def predict_match(
    match: dict[str, Any],
    ratings: dict[str, dict[str, Any]],
    allow_draw: bool = True,
) -> dict[str, Any]:
    """使用 Poisson 分布预测单场比分，并在淘汰赛平局时做强队决胜。"""

    home_id = match["home_team_id"]
    away_id = match["away_team_id"]
    home = ratings[home_id]
    away = ratings[away_id]
    rating_gap = home["overall_rating"] - away["overall_rating"]
    lambda_home = max(0.25, 1.35 + home["attack_strength"] * 0.9 - away["defense_strength"] * 0.45 + rating_gap * 0.35)
    lambda_away = max(0.25, 1.15 + away["attack_strength"] * 0.9 - home["defense_strength"] * 0.45 - rating_gap * 0.25)

    matrix = np.zeros((6, 6))
    for i in range(6):
        for j in range(6):
            matrix[i, j] = _poisson_pmf(i, lambda_home) * _poisson_pmf(j, lambda_away)
    matrix = matrix / matrix.sum()

    home_win_prob = float(np.tril(matrix, -1).sum())
    draw_prob = float(np.trace(matrix))
    away_win_prob = float(np.triu(matrix, 1).sum())
    best_home, best_away = np.unravel_index(int(matrix.argmax()), matrix.shape)

    if best_home > best_away:
        winner = home_id
    elif best_away > best_home:
        winner = away_id
    elif allow_draw:
        winner = None
    else:
        winner = home_id if home["overall_rating"] >= away["overall_rating"] else away_id

    flat_scores = [
        {"home_score": i, "away_score": j, "probability": round(float(matrix[i, j]), 4)}
        for i in range(6)
        for j in range(6)
    ]
    top_scores = sorted(flat_scores, key=lambda item: item["probability"], reverse=True)[:5]
    confidence = max(home_win_prob, draw_prob if allow_draw else 0, away_win_prob)
    confidence = min(0.95, confidence + abs(rating_gap) * 0.25)

    return {
        "match_id": match["match_id"],
        "stage": match["stage"],
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name": _team_name(home_id, ratings),
        "away_team_name": _team_name(away_id, ratings),
        "predicted_home_score": int(best_home),
        "predicted_away_score": int(best_away),
        "home_win_prob": round(home_win_prob, 4),
        "draw_prob": round(draw_prob, 4),
        "away_win_prob": round(away_win_prob, 4),
        "score_matrix": [[round(float(value), 4) for value in row] for row in matrix.tolist()],
        "top_scores": top_scores,
        "winner": winner,
        "winner_name": _team_name(winner, ratings) if winner else None,
        "confidence": round(float(confidence), 4),
        "key_factors": [
            f"{home['name']} 攻击强度 {home['attack_strength']:.2f}",
            f"{away['name']} 防守强度 {away['defense_strength']:.2f}",
            f"综合评分差 {rating_gap:.2f}",
            "淘汰赛平局时使用综合评分作为 tie-break" if not allow_draw else "小组赛允许 90 分钟平局",
        ],
    }
