from typing import Any

from app.model.match_predictor import predict_match


class SimulationAgent:
    """模拟工程师：只调用固定模拟器，不允许大模型自由写比分代码。"""

    name = "SimulationAgent"

    def run(self, match: dict[str, Any], ratings: dict[str, dict[str, Any]], allow_draw: bool) -> dict[str, Any]:
        prediction = predict_match(match, ratings, allow_draw=allow_draw)
        return {
            "agent": self.name,
            "summary": (
                f"固定 Poisson 模型输出 {prediction['home_team_name']} "
                f"{prediction['predicted_home_score']}-{prediction['predicted_away_score']} "
                f"{prediction['away_team_name']}。"
            ),
            "prediction": prediction,
        }
