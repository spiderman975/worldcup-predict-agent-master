from typing import Any


class CriticAgent:
    """一致性审核员：检查比分、胜者、解释是否自洽。"""

    name = "CriticAgent"

    def run(self, prediction: dict[str, Any], narration: dict[str, Any], allow_draw: bool) -> dict[str, Any]:
        warnings: list[str] = []
        errors: list[str] = []
        home_score = prediction["predicted_home_score"]
        away_score = prediction["predicted_away_score"]
        if not allow_draw and not prediction["winner"]:
            errors.append("淘汰赛预测缺少 winner。")
        if home_score > away_score and prediction["winner"] != prediction["home_team_id"]:
            errors.append("主队比分领先但 winner 不一致。")
        if away_score > home_score and prediction["winner"] != prediction["away_team_id"]:
            errors.append("客队比分领先但 winner 不一致。")
        if prediction["winner_name"] and prediction["winner_name"] not in narration["text"]:
            warnings.append("解释文本没有直接提到胜者名称。")
        if allow_draw and home_score == away_score and prediction["winner"] is not None:
            warnings.append("小组赛平局不应强制 winner。")
        return {
            "agent": self.name,
            "summary": "一致性审核通过。" if not errors else "一致性审核发现错误。",
            "passed": not errors,
            "warnings": warnings,
            "errors": errors,
        }
