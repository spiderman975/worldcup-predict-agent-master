from typing import Any

from app.services.data_scout_service import data_scout_service


def get_team_ratings_and_odds() -> dict[str, Any]:
    """Return team ratings derived only from the SQLite data layer."""

    teams = data_scout_service.list_teams()
    if not teams:
        raise RuntimeError("SQLite 数据库没有可用球队数据")

    rank_values = [int(team["fifa_rank"]) for team in teams]
    min_rank, max_rank = min(rank_values), max(rank_values)
    ratings: dict[str, dict[str, Any]] = {}

    for team in teams:
        inverse_fifa_rank = (max_rank - team["fifa_rank"]) / (max_rank - min_rank or 1)
        attack_defense_balance = (team["attack_score"] + team["defense_score"]) / 2
        squad = team.get("squad_availability_score", 0.8)
        strength = (
            0.25 * inverse_fifa_rank
            + 0.25 * team["attack_score"]
            + 0.25 * team["defense_score"]
            + 0.15 * team["recent_form"]
            + 0.10 * squad
        )
        ratings[team["team_id"]] = {
            "team_id": team["team_id"],
            "name": team["name"],
            "group": team["group"],
            "overall_rating": round(float(strength), 4),
            "attack_strength": round(float(team["attack_score"]), 4),
            "defense_strength": round(float(team["defense_score"]), 4),
            "form_score": round(float(team["recent_form"]), 4),
            "explanation_factors": [
                f"SQLite FIFA 排名逆向得分 {inverse_fifa_rank:.2f}",
                f"SQLite 阵容进攻 {team['attack_score']:.2f}",
                f"SQLite 阵容防守 {team['defense_score']:.2f}",
                f"攻防均衡 {attack_defense_balance:.2f}",
            ],
        }

    total_strength = sum(max(item["overall_rating"], 0.01) for item in ratings.values()) or 1
    odds = []
    for team_id, rating in ratings.items():
        implied_probability = max(rating["overall_rating"], 0.01) / total_strength
        odds.append(
            {
                "team_id": team_id,
                "team_name": rating["name"],
                "group": rating["group"],
                "overall_rating": rating["overall_rating"],
                "attack_strength": rating["attack_strength"],
                "defense_strength": rating["defense_strength"],
                "form_score": rating["form_score"],
                "implied_probability": round(implied_probability, 4),
                "decimal_odds": round(1 / implied_probability, 2),
                "explanation_factors": rating["explanation_factors"],
            }
        )
    return {"team_ratings": ratings, "team_odds": sorted(odds, key=lambda item: item["overall_rating"], reverse=True)}


def search_teams(query: str) -> list[dict[str, Any]]:
    """Search teams in the SQLite data layer only."""

    query_lower = query.lower().strip()
    teams = data_scout_service.list_teams()
    if not query_lower:
        return teams
    return [
        team
        for team in teams
        if query_lower in team["team_id"].lower()
        or query_lower in team["name"].lower()
        or query_lower == team["group"].lower()
    ]
