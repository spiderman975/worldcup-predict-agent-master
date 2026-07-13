from typing import Any


class FootballAnalystAgent:
    """足球分析师：把侦察数据转成可解释的强弱因素。"""

    name = "FootballAnalystAgent"

    def run(self, match: dict[str, Any], ratings: dict[str, dict[str, Any]], scout: dict[str, Any]) -> dict[str, Any]:
        home = ratings[match["home_team_id"]]
        away = ratings[match["away_team_id"]]
        rating_gap = home["overall_rating"] - away["overall_rating"]
        edge = home["name"] if rating_gap >= 0 else away["name"]
        home_db = scout.get("home", {}).get("database") or {}
        away_db = scout.get("away", {}).get("database") or {}
        factors = [
            f"{home['name']} 攻击强度 {home['attack_strength']:.2f}",
            f"{away['name']} 防守强度 {away['defense_strength']:.2f}",
            f"综合评分差 {rating_gap:.2f}",
            f"侦察信息：{scout['summary']}",
        ]
        if home_db:
            factors.append(f"{home_db['name']} 数据库阵容伤病 {len(home_db.get('injured_players', []))} 人")
        if away_db:
            factors.append(f"{away_db['name']} 数据库阵容伤病 {len(away_db.get('injured_players', []))} 人")

        return {
            "agent": self.name,
            "summary": (
                f"{home['name']} 综合评分 {home['overall_rating']:.2f}、攻击 {home['attack_strength']:.2f}；"
                f"{away['name']} 综合评分 {away['overall_rating']:.2f}、防守 {away['defense_strength']:.2f}。"
                f"综合优势暂时偏向 {edge}。"
            ),
            "rating_gap": round(rating_gap, 4),
            "factors": factors,
        }
