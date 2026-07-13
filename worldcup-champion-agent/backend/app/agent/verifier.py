from typing import Any


def verify_prediction(state: Any) -> dict[str, Any]:
    """回审预测结果与解释文本的一致性。"""

    warnings: list[str] = []
    errors: list[str] = []
    if state.champion_probabilities:
        top_team = state.champion_probabilities[0]["team_id"]
        if state.final_champion != top_team:
            errors.append("final_champion 与冠军概率第一名不一致。")
    for round_name, matches in state.knockout_results.items():
        if round_name == "champion":
            continue
        if isinstance(matches, list):
            for match in matches:
                if not match.get("winner"):
                    errors.append(f"{match.get('match_id')} 没有 winner。")
                hs = match.get("predicted_home_score")
                aw = match.get("predicted_away_score")
                if hs != aw and match.get("winner") not in {match.get("home_team_id"), match.get("away_team_id")}:
                    errors.append(f"{match.get('match_id')} winner 不在比赛双方中。")
    champion_name = state.team_ratings.get(state.final_champion or "", {}).get("name", "")
    if state.final_reasoning and champion_name and champion_name not in state.final_reasoning:
        warnings.append("推理文本未直接提到冠军队名称。")
    if not state.final_reasoning:
        errors.append("缺少 final_reasoning。")
    return {"passed": not errors, "warnings": warnings, "errors": errors}
