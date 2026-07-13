from app.model.tournament_simulator import simulate_tournament


def analyze_tournament(teams: list[dict], matches: list[dict], ratings: dict, runs: int) -> dict:
    """工具：调用锦标赛模拟器生成淘汰赛路径和冠军概率。"""

    return simulate_tournament(teams, matches, ratings, runs=runs)
