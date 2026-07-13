from app.model.match_predictor import predict_match


def test_predict_match_has_winner_for_knockout():
    """淘汰赛预测即使常规时间概率接近平局，也必须给出 winner。"""

    ratings = {
        "A": {"name": "A", "overall_rating": 0.8, "attack_strength": 0.8, "defense_strength": 0.8},
        "B": {"name": "B", "overall_rating": 0.7, "attack_strength": 0.75, "defense_strength": 0.75},
    }
    match = {"match_id": "T1", "stage": "final", "home_team_id": "A", "away_team_id": "B"}
    result = predict_match(match, ratings, allow_draw=False)
    assert result["winner"] in {"A", "B"}
