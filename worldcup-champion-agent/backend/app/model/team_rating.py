from typing import Any


def calculate_team_ratings(teams: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """根据 PDF 指定权重计算球队综合评分。"""

    if not teams:
        return {}
    elo_values = [float(team["elo_rating"]) for team in teams]
    rank_values = [int(team["fifa_rank"]) for team in teams]
    min_elo, max_elo = min(elo_values), max(elo_values)
    min_rank, max_rank = min(rank_values), max(rank_values)
    ratings: dict[str, dict[str, Any]] = {}
    for team in teams:
        normalized_elo = (team["elo_rating"] - min_elo) / (max_elo - min_elo or 1)
        inverse_fifa_rank = (max_rank - team["fifa_rank"]) / (max_rank - min_rank or 1)
        attack_defense_balance = (team["attack_score"] + team["defense_score"]) / 2
        squad = team.get("squad_availability_score", 0.8)
        strength = (
            0.30 * normalized_elo
            + 0.20 * inverse_fifa_rank
            + 0.20 * team["recent_form"]
            + 0.15 * attack_defense_balance
            + 0.10 * team["worldcup_history_score"]
            + 0.05 * squad
        )
        ratings[team["team_id"]] = {
            "team_id": team["team_id"],
            "name": team["name"],
            "group": team["group"],
            "overall_rating": round(float(strength), 4),
            "attack_strength": round(float(team["attack_score"] * (0.75 + normalized_elo * 0.35)), 4),
            "defense_strength": round(float(team["defense_score"] * (0.75 + normalized_elo * 0.35)), 4),
            "form_score": round(float(team["recent_form"]), 4),
            "explanation_factors": [
                f"ELO 归一化得分 {normalized_elo:.2f}",
                f"FIFA 排名逆向得分 {inverse_fifa_rank:.2f}",
                f"近期状态 {team['recent_form']:.2f}",
                f"攻防均衡 {attack_defense_balance:.2f}",
            ],
        }
    return ratings
