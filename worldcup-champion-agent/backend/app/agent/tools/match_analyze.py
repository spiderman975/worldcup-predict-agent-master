from app.model.match_predictor import predict_match


def analyze_match(match: dict, ratings: dict, allow_draw: bool = True) -> dict:
    """工具：调用 Poisson 模型预测单场比赛。"""

    return predict_match(match, ratings, allow_draw=allow_draw)
