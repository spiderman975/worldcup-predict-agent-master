from typing import Any


class FootballAnalystAgent:
    """足球分析师：把侦察数据转成可解释的强弱因素。"""

    name = "FootballAnalystAgent"

    def run(self, match: dict[str, Any], ratings: dict[str, dict[str, Any]], scout: dict[str, Any]) -> dict[str, Any]:
        home = ratings[match["home_team_id"]]
        away = ratings[match["away_team_id"]]
        rating_gap = home["overall_rating"] - away["overall_rating"]
        attack_gap = home["attack_strength"] - away["attack_strength"]
        defense_gap = home["defense_strength"] - away["defense_strength"]
        form_gap = home.get("recent_form", 0) - away.get("recent_form", 0)
        if abs(rating_gap) < 0.015:
            edge = "双方接近"
        else:
            edge = home["name"] if rating_gap > 0 else away["name"]
        home_db = scout.get("home", {}).get("database") or {}
        away_db = scout.get("away", {}).get("database") or {}
        factors = [
            f"进攻对比：{home['name']} {home['attack_strength']:.2f}，{away['name']} {away['attack_strength']:.2f}，差值 {attack_gap:+.2f}",
            f"防守对比：{home['name']} {home['defense_strength']:.2f}，{away['name']} {away['defense_strength']:.2f}，差值 {defense_gap:+.2f}",
            f"综合评分：{home['name']} {home['overall_rating']:.2f}，{away['name']} {away['overall_rating']:.2f}，差值 {rating_gap:+.2f}",
            f"近期状态差值 {form_gap:+.2f}",
            f"侦察信息：{scout['summary']}",
        ]
        if home_db:
            factors.append(f"{home_db['name']} 数据库阵容伤病 {len(home_db.get('injured_players', []))} 人")
        if away_db:
            factors.append(f"{away_db['name']} 数据库阵容伤病 {len(away_db.get('injured_players', []))} 人")

        return {
            "agent": self.name,
            "summary": (
                f"{home['name']} 综合 {home['overall_rating']:.2f}、进攻 {home['attack_strength']:.2f}、防守 {home['defense_strength']:.2f}；"
                f"{away['name']} 综合 {away['overall_rating']:.2f}、进攻 {away['attack_strength']:.2f}、防守 {away['defense_strength']:.2f}。"
                f"综合优势暂时偏向 {edge}。"
            ),
            "rating_gap": round(rating_gap, 4),
            "attack_gap": round(attack_gap, 4),
            "defense_gap": round(defense_gap, 4),
            "form_gap": round(form_gap, 4),
            "factors": factors,
        }
