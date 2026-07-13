from typing import Any


class NarratorAgent:
    """解说撰稿人：生成小组赛、淘汰赛、冠军解释中的单场解释。"""

    name = "NarratorAgent"

    def run(self, prediction: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        winner = prediction["winner_name"] or "平局"
        text = (
            f"{prediction['home_team_name']} 对阵 {prediction['away_team_name']}，模型给出的最可能比分是 "
            f"{prediction['predicted_home_score']}-{prediction['predicted_away_score']}，结果倾向为 {winner}。"
            f"关键原因是：{'；'.join(analysis['factors'][:3])}。"
            f"主胜/平局/客胜概率分别为 {prediction['home_win_prob']:.1%}、"
            f"{prediction['draw_prob']:.1%}、{prediction['away_win_prob']:.1%}。"
        )
        return {"agent": self.name, "summary": "已生成单场比分解释。", "text": text}
