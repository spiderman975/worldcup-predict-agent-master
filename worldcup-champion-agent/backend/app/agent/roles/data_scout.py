from typing import Any

from app.services.data_scout_service import data_scout_service


class DataScoutAgent:
    """数据侦察员：只整理 SQLite 数据库中的阵容、伤病、排名和赛程上下文。"""

    name = "DataScoutAgent"

    def run(self, match: dict[str, Any], teams: list[dict[str, Any]], ratings: dict[str, dict[str, Any]]) -> dict[str, Any]:
        home_raw = next(team for team in teams if team["team_id"] == match["home_team_id"])
        away_raw = next(team for team in teams if team["team_id"] == match["away_team_id"])
        home_db = data_scout_service.team_report(home_raw["name"]) or {}
        away_db = data_scout_service.team_report(away_raw["name"]) or {}
        db_context = data_scout_service.match_context(match, teams)
        search_query = f"{home_raw['name']} {away_raw['name']} {match.get('match_id', '')}"
        db_hits = data_scout_service.search_database(search_query, top_k=6)

        summary_parts = [
            f"SQLite 数据：{home_raw['name']} FIFA 排名 {home_raw['fifa_rank']}，评分 {ratings[home_raw['team_id']]['overall_rating']:.2f}",
            f"{away_raw['name']} FIFA 排名 {away_raw['fifa_rank']}，评分 {ratings[away_raw['team_id']]['overall_rating']:.2f}",
        ]
        if home_db:
            summary_parts.append(
                f"{home_db['name']} 计算进攻 {home_db['computed_attack']:.2f}，防守 {home_db['computed_defensive']:.2f}，伤病 {len(home_db['injured_players'])} 人"
            )
        if away_db:
            summary_parts.append(
                f"{away_db['name']} 计算进攻 {away_db['computed_attack']:.2f}，防守 {away_db['computed_defensive']:.2f}，伤病 {len(away_db['injured_players'])} 人"
            )

        return {
            "agent": self.name,
            "summary": "；".join(summary_parts) + "。",
            "sources": ["SQLite data/worldcup.db"],
            "home": {**home_raw, "database": home_db},
            "away": {**away_raw, "database": away_db},
            "database_match": db_context.get("database_match"),
            "database_search_results": db_hits,
        }
