from app.services.data_scout_service import data_scout_service
from app.services.match_prediction_service import list_schedule


def get_all_teams() -> list[dict]:
    """查询 SQLite 中的全部球队。"""

    return data_scout_service.list_teams()


def get_matches() -> list[dict]:
    """查询 SQLite 中的全部赛程。"""

    return list_schedule()
