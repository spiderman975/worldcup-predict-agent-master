from typing import Any

from app.services.vector_store import match_explanation_store


def store_match_explanation(prediction: dict[str, Any], text: str) -> dict[str, Any]:
    """把单场比赛解释写入本地向量库。"""

    metadata = {
        "match_id": prediction["match_id"],
        "stage": prediction["stage"],
        "home_team_id": prediction["home_team_id"],
        "away_team_id": prediction["away_team_id"],
        "winner": prediction["winner"],
    }
    match_explanation_store.upsert(prediction["match_id"], text, metadata)
    return {"match_id": prediction["match_id"], "stage": prediction["stage"], "text": text, "metadata": metadata}


def build_match_explanation(prediction: dict[str, Any], ratings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """兼容旧调用：为单场比赛生成中文解释，并写入本地向量库。"""

    home = ratings[prediction["home_team_id"]]
    away = ratings[prediction["away_team_id"]]
    winner_name = prediction["winner_name"] or "平局"
    score = f"{prediction['predicted_home_score']}-{prediction['predicted_away_score']}"
    text = (
        f"{prediction['stage']} 阶段 {prediction['home_team_name']} 对阵 {prediction['away_team_name']}，"
        f"Poisson 模型最可能比分为 {score}，预测结果为 {winner_name}。"
        f"{prediction['home_team_name']} 的综合评分为 {home['overall_rating']:.2f}，攻击强度 {home['attack_strength']:.2f}；"
        f"{prediction['away_team_name']} 的综合评分为 {away['overall_rating']:.2f}，防守强度 {away['defense_strength']:.2f}。"
        f"主胜概率 {prediction['home_win_prob']:.1%}，平局概率 {prediction['draw_prob']:.1%}，"
        f"客胜概率 {prediction['away_win_prob']:.1%}。"
        f"关键判断依据包括：{'；'.join(prediction.get('key_factors', []))}。"
    )
    return store_match_explanation(prediction, text)


def search_match_explanations(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    """检索已生成的比赛解释。"""

    return match_explanation_store.search(query, top_k=top_k)
