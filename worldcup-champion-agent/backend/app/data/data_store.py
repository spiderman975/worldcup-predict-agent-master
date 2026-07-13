import json
from pathlib import Path
from typing import Any

from app.data.data_collector import PROJECT_ROOT, load_processed_data
from app.data.data_preprocessor import normalize_features


class DataStore:
    """封装本地数据访问，后续接外部数据源时保持上层调用不变。"""

    def __init__(self) -> None:
        teams, matches, features = load_processed_data()
        self.teams = normalize_features(teams)
        self.matches = matches
        self.team_features = features
        self.snapshot_dir = PROJECT_ROOT / "data" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def get_all_teams(self) -> list[dict[str, Any]]:
        """返回全部球队。"""

        return self.teams

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        """按球队 ID 查询球队。"""

        return next((team for team in self.teams if team["team_id"] == team_id), None)

    def get_matches(self) -> list[dict[str, Any]]:
        """返回全部赛程。"""

        return self.matches

    def get_matches_by_stage(self, stage: str) -> list[dict[str, Any]]:
        """按阶段查询赛程，例如 group、quarter、semi、final。"""

        return [match for match in self.matches if match["stage"] == stage]

    def get_group_teams(self, group: str) -> list[dict[str, Any]]:
        """查询某个小组的球队。"""

        return [team for team in self.teams if team["group"] == group]

    def save_snapshot(self, run_id: str, state: dict[str, Any]) -> Path:
        """把一次预测任务完整结果保存为 JSON，方便前端或后续审计读取。"""

        path = self.snapshot_dir / f"{run_id}.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def load_run_result(self, run_id: str) -> dict[str, Any] | None:
        """读取某次预测任务的 JSON snapshot。"""

        path = self.snapshot_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


data_store = DataStore()
