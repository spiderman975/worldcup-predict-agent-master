from app.agent.state import PredictionState


RUNS: dict[str, PredictionState] = {}


async def create_prediction_run(
    monte_carlo_runs: int,
    mode: str = "full",
    knockout_round: str | None = None,
    group_round: int | None = None,
) -> PredictionState:
    raise RuntimeError("旧 demo 整届预测服务已停用；当前只保留 SQLite 新数据的单场预测流程。")


def get_prediction_run(run_id: str) -> dict | None:
    return RUNS.get(run_id).model_dump(mode="json") if run_id in RUNS else None


async def cancel_prediction_run(run_id: str) -> bool:
    return False
