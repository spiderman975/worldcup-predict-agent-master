from app.model.tournament_simulator import simulate_tournament


def run_simulation(teams: list[dict], matches: list[dict], ratings: dict, runs: int) -> dict:
    """服务层包装锦标赛模拟，便于后续替换异步或分布式实现。"""

    return simulate_tournament(teams, matches, ratings, runs)
