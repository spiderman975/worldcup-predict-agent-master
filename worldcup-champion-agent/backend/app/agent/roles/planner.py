from typing import Any


class PlannerAgent:
    """预测规划师：拆解单场预测需要的数据、模型和校验步骤。"""

    name = "PlannerAgent"

    def run(self, match: dict[str, Any], ratings: dict[str, dict[str, Any]]) -> dict[str, Any]:
        home = ratings[match["home_team_id"]]
        away = ratings[match["away_team_id"]]
        return {
            "agent": self.name,
            "summary": (
                f"拆解 {home['name']} vs {away['name']}：需要综合评分、攻防强度、近期状态、"
                "数据库侦察、Poisson 比分矩阵和胜者校验。"
            ),
            "plan": ["读取球队评分", "检索数据库侦察信息", "汇总近期和攻防信息", "调用固定模拟器", "生成解释", "一致性审核"],
        }
