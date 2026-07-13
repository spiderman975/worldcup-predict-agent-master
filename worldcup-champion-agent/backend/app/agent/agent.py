import asyncio
from collections import defaultdict
from typing import Any, Literal

from app.agent.match_pipeline import MatchPredictionPipeline
from app.agent.reasoning_generator import generate_reasoning
from app.agent.state import PredictionState
from app.agent.tools.football_query import get_all_teams, get_matches
from app.agent.verifier import verify_prediction
from app.core.config import get_settings
from app.data.data_store import data_store
from app.model.tournament_simulator import build_knockout_matches, simulate_tournament
from app.services.stream_service import stream_service
from app.services.team_analysis_service import get_team_ratings_and_odds

RunMode = Literal["full", "ratings", "group", "group_round", "knockout", "champion"]


class PredictionAgent:
    """世界杯预测总编排器。

    单场比赛仍按固定多 Agent 流水线执行：
    PlannerAgent -> DataScoutAgent -> FootballAnalystAgent -> SimulationAgent
    -> NarratorAgent -> CriticAgent。
    """

    def __init__(
        self,
        run_id: str,
        monte_carlo_runs: int = 1000,
        mode: RunMode = "full",
        knockout_round: str | None = None,
        group_round: int | None = None,
    ) -> None:
        self.state = PredictionState(run_id=run_id)
        self.monte_carlo_runs = monte_carlo_runs
        self.mode = mode
        self.knockout_round = knockout_round or "final"
        self.group_round = group_round or 1
        self.pipeline = MatchPredictionPipeline(self._emit)
        concurrency = max(1, get_settings().match_prediction_concurrency)
        self.match_semaphore = asyncio.Semaphore(concurrency)

    async def _emit(self, event: str, message: str, phase: str | None = None, data: dict[str, Any] | None = None) -> None:
        """记录 Agent 节点并推送 SSE。"""

        payload = {"event": event, "phase": phase, "message": message, "data": data or {}}
        self.state.reasoning_steps.append(payload)
        await stream_service.publish(self.state.run_id, event, message, phase, data)

    async def _load_data(self) -> None:
        """加载本地球队、赛程和特征数据。"""

        self.state.touch("DATA_LOADING")
        await self._emit("agent_thought", "PlannerAgent 正在确认预测任务所需的数据入口。", "DATA_LOADING")
        self.state.teams = get_all_teams()
        self.state.matches = get_matches()
        self.state.team_features = data_store.team_features
        await self._emit(
            "data_loaded",
            f"已加载 {len(self.state.teams)} 支球队和 {len(self.state.matches)} 场小组赛。",
            "DATA_LOADING",
            {"teams": self.state.teams, "matches": self.state.matches},
        )

    async def _rate_teams(self) -> None:
        """计算球队综合评分和展示赔率。"""

        self.state.touch("TEAM_RATING")
        await self._emit(
            "agent_node",
            "FootballAnalystAgent 正在构建球队综合实力评分。",
            "TEAM_RATING",
            {"agent": "FootballAnalystAgent"},
        )
        analysis = get_team_ratings_and_odds()
        self.state.team_ratings = analysis["team_ratings"]
        self.state.team_odds = analysis["team_odds"]
        for row in self.state.team_odds[:8]:
            await self._emit(
                "team_rating",
                f"{row['team_name']} 综合评分 {row['overall_rating']:.2f}，展示赔率 {row['decimal_odds']:.2f}。",
                "TEAM_RATING",
                {"team": row},
            )
            await asyncio.sleep(0.02)
        await self._emit(
            "team_rating_complete",
            "球队评分与展示赔率计算完成。",
            "TEAM_RATING",
            {"team_ratings": self.state.team_ratings, "team_odds": self.state.team_odds},
        )

    def _empty_group_tables(self) -> dict[str, dict[str, dict[str, Any]]]:
        """初始化小组积分表。"""

        tables: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for team in self.state.teams:
            tables[team["group"]][team["team_id"]] = {
                "team_id": team["team_id"],
                "team_name": team["name"],
                "played": 0,
                "points": 0,
                "goals_for": 0,
                "goals_against": 0,
                "goal_difference": 0,
                "qualified": False,
                "rank": 0,
            }
        return tables

    @staticmethod
    def _group_round(match: dict[str, Any]) -> int:
        """按每组循环赛 6 场拆成三轮：1/6、2/5、3/4。"""

        digits = "".join(ch for ch in match["match_id"] if ch.isdigit())
        number = int(digits or "0")
        if number in {1, 6}:
            return 1
        if number in {2, 5}:
            return 2
        return 3

    def _apply_group_prediction(
        self,
        tables: dict[str, dict[str, dict[str, Any]]],
        match: dict[str, Any],
        prediction: dict[str, Any],
    ) -> None:
        """把一场小组赛比分写入积分表。"""

        home_row = tables[match["group"]][match["home_team_id"]]
        away_row = tables[match["group"]][match["away_team_id"]]
        hs = prediction["predicted_home_score"]
        aw = prediction["predicted_away_score"]
        home_row["played"] += 1
        away_row["played"] += 1
        home_row["goals_for"] += hs
        home_row["goals_against"] += aw
        away_row["goals_for"] += aw
        away_row["goals_against"] += hs
        if hs > aw:
            home_row["points"] += 3
        elif aw > hs:
            away_row["points"] += 3
        else:
            home_row["points"] += 1
            away_row["points"] += 1

    def _finalize_group_tables(self, tables: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
        """生成排名、小组出线队和小组第三排行榜。"""

        group_tables: dict[str, list[dict[str, Any]]] = {}
        qualified: dict[str, list[str]] = {}
        third_place_rows: list[dict[str, Any]] = []
        for group, rows in tables.items():
            sorted_rows = sorted(
                rows.values(),
                key=lambda row: (
                    row["points"],
                    row["goals_for"] - row["goals_against"],
                    row["goals_for"],
                    self.state.team_ratings[row["team_id"]]["overall_rating"],
                ),
                reverse=True,
            )
            qualified[group] = []
            for rank, row in enumerate(sorted_rows, start=1):
                row["goal_difference"] = row["goals_for"] - row["goals_against"]
                row["rank"] = rank
                row["qualified"] = rank <= 2
                if row["qualified"]:
                    qualified[group].append(row["team_id"])
                if rank == 3:
                    third_place_rows.append({**row, "group": group})
            group_tables[group] = sorted_rows
        third_place_ranking = sorted(
            third_place_rows,
            key=lambda row: (row["points"], row["goal_difference"], row["goals_for"], self.state.team_ratings[row["team_id"]]["overall_rating"]),
            reverse=True,
        )
        for rank, row in enumerate(third_place_ranking, start=1):
            row["third_rank"] = rank
        return {"group_tables": group_tables, "qualified": qualified, "third_place_ranking": third_place_ranking}

    async def _predict_group_match(self, match: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """并发执行单场小组赛预测。"""

        async with self.match_semaphore:
            await self._emit(
                "match_pipeline_start",
                f"开始预测 {match['home_team_id']} vs {match['away_team_id']}。",
                "GROUP_STAGE",
                {"match": match},
            )
            prediction, explanation = await self.pipeline.predict(
                match,
                self.state.teams,
                self.state.team_ratings,
                allow_draw=True,
                phase="GROUP_STAGE",
            )
            return match, prediction, explanation

    async def _run_group_stage(self) -> None:
        """按轮次并发执行小组赛多 Agent 预测。"""

        self.state.touch("GROUP_STAGE")
        await self._emit("phase", "进入小组赛：每轮比赛并行预测，每场仍经过六个 Agent 节点。", "GROUP_STAGE")
        tables = self._empty_group_tables()
        predictions: list[dict[str, Any]] = []
        group_matches = [item for item in self.state.matches if item["stage"] == "group"]

        for round_number in (1, 2, 3):
            round_matches = [match for match in group_matches if self._group_round(match) == round_number]
            await self._emit(
                "group_round_start",
                f"正在并行预测小组赛第 {round_number} 轮，共 {len(round_matches)} 场比赛。",
                "GROUP_STAGE",
                {"round": round_number, "matches": round_matches},
            )
            tasks = [asyncio.create_task(self._predict_group_match(match)) for match in round_matches]
            for completed in asyncio.as_completed(tasks):
                match, prediction, explanation = await completed
                self._apply_group_prediction(tables, match, prediction)
                predictions.append(prediction)
                self.state.match_explanations.append(explanation)
                await self._emit(
                    "group_match_predicted",
                    f"{prediction['home_team_name']} {prediction['predicted_home_score']}-{prediction['predicted_away_score']} {prediction['away_team_name']}：{prediction['winner_name'] or '平局'}。",
                    "GROUP_STAGE",
                    {"round": round_number, "match": prediction, "explanation": explanation},
                )
                await self._emit(
                    "animation_step",
                    f"小组赛动画更新：{prediction['match_id']} 已完成。",
                    "GROUP_STAGE",
                    {"stage": "group", "round": round_number, "match_id": prediction["match_id"]},
                )
            await self._emit("group_round_complete", f"小组赛第 {round_number} 轮已完成。", "GROUP_STAGE", {"round": round_number})

        finalized = self._finalize_group_tables(tables)
        self.state.group_results = {**finalized, "group_stage_predictions": predictions}
        self.state.group_third_ranking = finalized["third_place_ranking"]
        await self._emit(
            "group_prediction",
            "小组赛积分榜和小组第三排行榜已生成。",
            "GROUP_STAGE",
            {"group_results": self.state.group_results, "third_place_ranking": self.state.group_third_ranking},
        )

    async def _run_group_round(self, round_number: int) -> None:
        """只执行指定一轮小组赛预测，前端负责累计已完成轮次。"""

        self.state.touch("GROUP_STAGE")
        tables = self._empty_group_tables()
        predictions: list[dict[str, Any]] = []
        group_matches = [item for item in self.state.matches if item["stage"] == "group"]
        round_matches = [match for match in group_matches if self._group_round(match) == round_number]
        await self._emit(
            "group_round_start",
            f"正在并行预测小组赛第 {round_number} 轮，共 {len(round_matches)} 场比赛。",
            "GROUP_STAGE",
            {"round": round_number, "matches": round_matches},
        )
        tasks = [asyncio.create_task(self._predict_group_match(match)) for match in round_matches]
        for completed in asyncio.as_completed(tasks):
            match, prediction, explanation = await completed
            self._apply_group_prediction(tables, match, prediction)
            predictions.append(prediction)
            self.state.match_explanations.append(explanation)
            await self._emit(
                "group_match_predicted",
                f"{prediction['home_team_name']} {prediction['predicted_home_score']}-{prediction['predicted_away_score']} {prediction['away_team_name']}：{prediction['winner_name'] or '平局'}。",
                "GROUP_STAGE",
                {"round": round_number, "match": prediction, "explanation": explanation},
            )
            await self._emit(
                "animation_step",
                f"小组赛动画更新：{prediction['match_id']} 已完成。",
                "GROUP_STAGE",
                {"stage": "group", "round": round_number, "match_id": prediction["match_id"]},
            )
        self.state.group_results = {"group_stage_predictions": predictions}
        await self._emit("group_round_complete", f"小组赛第 {round_number} 轮已完成。", "GROUP_STAGE", {"round": round_number})

    async def _run_knockout(self, target_round: str = "final") -> None:
        """逐轮执行淘汰赛多 Agent 预测。"""

        if not self.state.group_results:
            await self._run_group_stage()
        self.state.touch("KNOCKOUT")
        await self._emit("phase", f"进入淘汰赛：目标阶段 {target_round}。", "KNOCKOUT")

        quarters = build_knockout_matches(self.state.group_results["qualified"])
        quarter_predictions: list[dict[str, Any]] = []
        semi_predictions: list[dict[str, Any]] = []
        final_predictions: list[dict[str, Any]] = []

        await self._emit("knockout_round_start", "开始分析 1/4 决赛。", "KNOCKOUT", {"round": "quarter"})
        for match in quarters:
            prediction, explanation = await self.pipeline.predict(match, self.state.teams, self.state.team_ratings, allow_draw=False, phase="KNOCKOUT")
            quarter_predictions.append(prediction)
            self.state.match_explanations.append(explanation)
            await self._emit("knockout_match_predicted", f"1/4 决赛：{prediction['winner_name']} 晋级。", "KNOCKOUT", {"round": "quarter", "match": prediction, "explanation": explanation})

        if target_round == "quarter":
            self.state.knockout_results = {"quarter": quarter_predictions, "champion": None}
            await self._emit("bracket_update", "1/4 决赛对阵树已更新。", "KNOCKOUT", {"knockout_results": self.state.knockout_results})
            return

        semis = [
            {**quarters[0], "match_id": "SF1", "stage": "semi", "home_team_id": quarter_predictions[0]["winner"], "away_team_id": quarter_predictions[1]["winner"]},
            {**quarters[2], "match_id": "SF2", "stage": "semi", "home_team_id": quarter_predictions[2]["winner"], "away_team_id": quarter_predictions[3]["winner"]},
        ]
        await self._emit("knockout_round_start", "开始分析 1/2 决赛。", "KNOCKOUT", {"round": "semi"})
        for match in semis:
            prediction, explanation = await self.pipeline.predict(match, self.state.teams, self.state.team_ratings, allow_draw=False, phase="KNOCKOUT")
            semi_predictions.append(prediction)
            self.state.match_explanations.append(explanation)
            await self._emit("knockout_match_predicted", f"1/2 决赛：{prediction['winner_name']} 晋级。", "KNOCKOUT", {"round": "semi", "match": prediction, "explanation": explanation})

        if target_round == "semi":
            self.state.knockout_results = {"quarter": quarter_predictions, "semi": semi_predictions, "champion": None}
            await self._emit("bracket_update", "1/2 决赛对阵树已更新。", "KNOCKOUT", {"knockout_results": self.state.knockout_results})
            return

        final_match = {
            **semis[0],
            "match_id": "F1",
            "stage": "final",
            "home_team_id": semi_predictions[0]["winner"],
            "away_team_id": semi_predictions[1]["winner"],
        }
        await self._emit("knockout_round_start", "开始分析决赛。", "KNOCKOUT", {"round": "final"})
        final_prediction, final_explanation = await self.pipeline.predict(final_match, self.state.teams, self.state.team_ratings, allow_draw=False, phase="KNOCKOUT")
        final_predictions.append(final_prediction)
        self.state.match_explanations.append(final_explanation)
        self.state.final_champion = final_prediction["winner"]
        await self._emit("knockout_match_predicted", f"决赛完成：{final_prediction['winner_name']} 夺冠路径确认。", "KNOCKOUT", {"round": "final", "match": final_prediction, "explanation": final_explanation})

        self.state.knockout_results = {
            "quarter": quarter_predictions,
            "semi": semi_predictions,
            "final": final_predictions,
            "champion": final_prediction["winner"],
        }
        await self._emit("bracket_update", "淘汰赛对阵树已更新。", "KNOCKOUT", {"knockout_results": self.state.knockout_results})

    async def _run_champion_probability(self) -> None:
        """运行 Monte Carlo 冠军概率模拟。"""

        self.state.touch("PROBABILITY")
        await self._emit("phase", f"SimulationAgent 开始运行 {self.monte_carlo_runs} 次 Monte Carlo 冠军概率模拟。", "PROBABILITY")
        simulation = await asyncio.to_thread(
            simulate_tournament,
            self.state.teams,
            self.state.matches,
            self.state.team_ratings,
            self.monte_carlo_runs,
        )
        if not self.state.group_results:
            self.state.group_results = simulation["group_results"]
            self.state.group_third_ranking = self.state.group_results.get("third_place_ranking", [])
        if not self.state.knockout_results:
            self.state.knockout_results = simulation["knockout_results"]
        self.state.champion_probabilities = simulation["champion_probabilities"]
        self.state.round_reach_probabilities = simulation["round_reach_probabilities"]
        self.state.final_champion = simulation["final_champion"]
        await self._emit(
            "champion_probability",
            "冠军概率排行榜已生成。",
            "PROBABILITY",
            {
                "champion_probabilities": self.state.champion_probabilities,
                "round_reach_probabilities": self.state.round_reach_probabilities,
                "final_champion": self.state.final_champion,
            },
        )

    async def _run_reasoning_and_verify(self) -> None:
        """生成最终推理并回审一致性。"""

        self.state.touch("REASONING")
        await self._emit("agent_node", "NarratorAgent 正在整理最终冠军叙事。", "REASONING", {"agent": "NarratorAgent"})
        if self.state.final_champion:
            self.state.final_reasoning = await asyncio.to_thread(
                generate_reasoning,
                self.state.final_champion,
                self.state.champion_probabilities,
                self.state.group_results,
                self.state.knockout_results,
                self.state.team_ratings,
            )
            await self._emit("reasoning", "NarratorAgent 已生成最终冠军推理。", "REASONING", {"final_reasoning": self.state.final_reasoning})

        self.state.touch("VERIFY")
        self.state.verifier_result = verify_prediction(self.state)
        await self._emit("verify", "CriticAgent 已完成全局一致性审核。", "VERIFY", {"verifier_result": self.state.verifier_result})

    async def run(self) -> PredictionState:
        """按任务模式执行预测。"""

        try:
            self.state.status = "running"
            await self._emit("prediction_start", f"预测任务已启动，模式：{self.mode}。", "START")
            await self._load_data()
            await self._rate_teams()

            if self.mode == "ratings":
                pass
            elif self.mode == "group":
                await self._run_group_stage()
            elif self.mode == "group_round":
                await self._run_group_round(self.group_round)
            elif self.mode == "knockout":
                await self._run_group_stage()
                await self._run_knockout(self.knockout_round)
            elif self.mode == "champion":
                await self._run_champion_probability()
            else:
                await self._run_group_stage()
                await self._run_knockout("final")
                await self._run_champion_probability()
                await self._run_reasoning_and_verify()

            self.state.predicted_matches = (
                self.state.group_results.get("group_stage_predictions", [])
                + self.state.knockout_results.get("quarter", [])
                + self.state.knockout_results.get("semi", [])
                + self.state.knockout_results.get("final", [])
            )
            self.state.status = "completed"
            self.state.touch("COMPLETED")
            data_store.save_snapshot(self.state.run_id, self.state.model_dump(mode="json"))
            await self._emit("prediction_complete", "预测任务完成。", "COMPLETED", self.state.model_dump(mode="json"))
            return self.state
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.status = "failed"
            self.state.errors.append(str(exc))
            data_store.save_snapshot(self.state.run_id, self.state.model_dump(mode="json"))
            await self._emit("prediction_error", f"预测任务失败：{exc}", "FAILED", {"errors": self.state.errors})
            raise
