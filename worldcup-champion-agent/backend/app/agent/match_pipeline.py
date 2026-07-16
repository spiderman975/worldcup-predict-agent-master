import json
from typing import Any, Awaitable, Callable

from app.agent.roles import (
    CriticAgent,
    DataScoutAgent,
    FootballAnalystAgent,
    NarratorAgent,
    PlannerAgent,
    SimulationAgent,
)
from app.services.llm_service import llm_service
from app.services.match_reasoning_service import store_match_explanation

EmitFn = Callable[[str, str, str | None, dict[str, Any] | None], Awaitable[None]]


class MatchPredictionPipeline:
    """单场比赛多 Agent 预测流水线。

    规则模拟器是稳定底座；LLM 只增强规划、侦察摘要、分析解释、撰稿和审核，
    不直接改写比分、概率或胜者。
    """

    def __init__(self, emit: EmitFn) -> None:
        self.emit = emit
        self.planner = PlannerAgent()
        self.scout = DataScoutAgent()
        self.analyst = FootballAnalystAgent()
        self.simulator = SimulationAgent()
        self.narrator = NarratorAgent()
        self.critic = CriticAgent()

    @staticmethod
    def _clip_text(text: Any, max_len: int = 68) -> str:
        """把面向用户的 SSE 文案限制成短句，避免内部字段刷屏。"""

        cleaned = " ".join(str(text or "").replace("\n", " ").split())
        return cleaned if len(cleaned) <= max_len else f"{cleaned[:max_len]}..."

    def _public_summary(self, result: dict[str, Any]) -> str:
        """把各 Agent 的详细结果转成通俗短摘要。"""

        agent = result.get("agent")
        if agent == "PlannerAgent":
            return "已规划好本场预测步骤。"
        if agent == "DataScoutAgent":
            return "已整理双方基础数据。"
        if agent == "FootballAnalystAgent":
            gap = result.get("rating_gap")
            return f"已完成强弱分析，评分差约 {gap}。" if gap is not None else "已完成双方强弱分析。"
        if agent == "SimulationAgent":
            return self._clip_text(result.get("summary"), 72)
        if agent == "NarratorAgent":
            return "已生成本场比分解释。"
        if agent == "CriticAgent":
            errors = result.get("errors") or []
            warnings = result.get("warnings") or []
            if result.get("passed"):
                return "审核通过：比分、胜者和解释基本一致。"
            if errors:
                return f"审核发现 {len(errors)} 个关键问题，已保留详细记录。"
            if warnings:
                return f"审核有 {len(warnings)} 条提醒，但不影响预测结果。"
            return "审核完成。"
        return self._clip_text(result.get("summary"), 72)

    async def _emit_agent(self, result: dict[str, Any], match: dict[str, Any], phase: str) -> None:
        """把 Agent 节点推送给前端。"""

        await self.emit(
            "agent_node",
            f"{result['agent']}：{self._public_summary(result)}",
            phase,
            {
                "agent": result["agent"],
                "summary": self._public_summary(result),
                "raw_summary": result.get("summary"),
                "match_id": match["match_id"],
                "detail": result,
            },
        )

    async def _emit_llm_status(self, agent_name: str, match: dict[str, Any], phase: str, message: str) -> None:
        """展示大模型增强过程。"""

        await self.emit(
            "agent_node",
            f"{agent_name} {self._clip_text(message, 54)}",
            phase,
            {"agent": agent_name, "match_id": match["match_id"], "llm_enabled": llm_service.agent_enabled(agent_name)},
        )

    def _system_prompt(self, agent_name: str) -> str:
        """按 Agent 角色生成更严格的系统提示词。"""

        role_rules = {
            "PlannerAgent": (
                "你是预测规划师。职责是拆解预测任务、识别需要读取的数据和需要调用的模型，"
                "并指出后续 Agent 的校验重点。不得输出比分结论。"
            ),
            "DataScoutAgent": (
                "你是数据侦察员。职责是基于已给出的本地数据总结双方排名、状态、攻防与阵容可用性。"
                "当前没有联网搜索结果时，必须明确说明数据来自本地缓存，不得声称查到了实时新闻或伤病。"
            ),
            "FootballAnalystAgent": (
                "你是足球分析师。职责是把评分、进攻、防守、近期状态和侦察摘要转化为强弱因素。"
                "必须区分确定数据和模型推断，不得把主观判断写成事实。"
            ),
            "NarratorAgent": (
                "你是解说撰稿人。职责是把固定模拟器给出的比分、胜平负概率和分析因素写成中文解释。"
                "不得改动比分、胜者、概率；必须让解释能被普通用户理解。"
            ),
            "CriticAgent": (
                "你是一致性审核员。职责是检查预测路径、比分、胜者、概率、解释文本是否自洽。"
                "规则校验发现的错误必须保留，不能为了让结果通过而删除错误。"
                "summary 必须面向普通用户，30 字以内，不要输出字段名、公式、数组或长编号列表。"
            ),
        }
        return (
            f"{role_rules[agent_name]}\n"
            "通用约束：\n"
            "1. 只基于用户提供的 JSON 上下文和规则版输出推理。\n"
            "2. 不得编造未提供的球员伤病、真实新闻、赔率来源、比分概率或球队数据。\n"
            "3. 如果信息不足，用“基于当前本地数据”表述不确定性。\n"
            "4. 输出必须是严格 JSON 对象，不要 Markdown，不要代码块，不要额外解释。\n"
            "5. 中文表达要严谨、简洁、可读，避免夸张断言。"
        )

    async def _enhance_with_llm(
        self,
        *,
        agent_name: str,
        result: dict[str, Any],
        match: dict[str, Any],
        phase: str,
        context: dict[str, Any],
        output_contract: str,
    ) -> dict[str, Any]:
        """在规则结果基础上尝试调用 LLM，失败时保留规则结果。"""

        if not llm_service.agent_enabled(agent_name):
            result["llm_used"] = False
            return result

        await self._emit_llm_status(agent_name, match, phase, "正在调用大模型增强节点输出...")
        user_prompt = (
            f"当前 Agent：{agent_name}\n"
            f"输出契约：{output_contract}\n"
            "规则版输出：\n"
            f"{json.dumps(result, ensure_ascii=False)}\n"
            "结构化上下文：\n"
            f"{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        try:
            enhanced = await llm_service.complete_json(system_prompt=self._system_prompt(agent_name), user_prompt=user_prompt)
        except Exception as exc:
            result["llm_used"] = False
            result["llm_error"] = llm_service.describe_error(exc)
            await self._emit_llm_status(agent_name, match, phase, f"大模型增强失败，已回退规则输出：{result['llm_error']}")
            return result

        merged = {**result, **{key: value for key, value in enhanced.items() if value is not None}}
        merged["agent"] = agent_name
        merged["llm_used"] = True
        if "summary" not in merged:
            merged["summary"] = result.get("summary", "大模型已完成节点增强。")
        return merged

    @staticmethod
    def _as_text_list(value: Any, fallback: list[str] | None = None) -> list[str]:
        """把模型可能返回的字符串、列表或空值统一成字符串列表。"""

        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return fallback or []

    async def _enhance_plan(self, plan: dict[str, Any], match: dict[str, Any], ratings: dict[str, dict[str, Any]], phase: str) -> dict[str, Any]:
        enhanced = await self._enhance_with_llm(
            agent_name="PlannerAgent",
            result=plan,
            match=match,
            phase=phase,
            context={"match": match, "home_rating": ratings[match["home_team_id"]], "away_rating": ratings[match["away_team_id"]]},
            output_contract='返回 {"summary": "...", "plan": ["...", "..."]}。plan 应覆盖数据、特征、模拟、解释、审核，控制在 5-7 步。',
        )
        enhanced["plan"] = self._as_text_list(enhanced.get("plan"), plan["plan"])
        return enhanced

    async def _enhance_scout(self, scout: dict[str, Any], match: dict[str, Any], phase: str) -> dict[str, Any]:
        enhanced = await self._enhance_with_llm(
            agent_name="DataScoutAgent",
            result=scout,
            match=match,
            phase=phase,
            context={"match": match, "home": scout["home"], "away": scout["away"], "sources": scout["sources"]},
            output_contract='返回 {"summary": "...", "search_notes": ["...", "..."]}。必须说明数据来自本地缓存，不能写实时搜索结论。',
        )
        enhanced["sources"] = self._as_text_list(enhanced.get("sources"), scout["sources"])
        enhanced["search_notes"] = self._as_text_list(enhanced.get("search_notes"))
        return enhanced

    async def _enhance_analysis(
        self,
        analysis: dict[str, Any],
        match: dict[str, Any],
        ratings: dict[str, dict[str, Any]],
        scout: dict[str, Any],
        phase: str,
    ) -> dict[str, Any]:
        enhanced = await self._enhance_with_llm(
            agent_name="FootballAnalystAgent",
            result=analysis,
            match=match,
            phase=phase,
            context={
                "match": match,
                "home_rating": ratings[match["home_team_id"]],
                "away_rating": ratings[match["away_team_id"]],
                "scout": scout,
            },
            output_contract='返回 {"summary": "...", "factors": ["...", "..."], "rating_gap": 数值}。factors 要覆盖攻防、状态、评分差和不确定性。',
        )
        enhanced["factors"] = self._as_text_list(enhanced.get("factors"), analysis["factors"])
        return enhanced

    async def _enhance_narration(
        self,
        narration: dict[str, Any],
        prediction: dict[str, Any],
        analysis: dict[str, Any],
        match: dict[str, Any],
        phase: str,
    ) -> dict[str, Any]:
        enhanced = await self._enhance_with_llm(
            agent_name="NarratorAgent",
            result=narration,
            match=match,
            phase=phase,
            context={"prediction": prediction, "analysis": analysis},
            output_contract=(
                '返回 {"summary": "...", "text": "..."}。text 必须包含双方球队名、预测比分、胜平负概率、'
                "2-4 个关键依据和一句不确定性说明。不得改变 prediction 中的任何数值。"
            ),
        )
        if not isinstance(enhanced.get("text"), str) or not enhanced["text"].strip():
            enhanced["text"] = narration["text"]
        return enhanced

    async def _enhance_critic(
        self,
        critic: dict[str, Any],
        prediction: dict[str, Any],
        narration: dict[str, Any],
        match: dict[str, Any],
        allow_draw: bool,
        phase: str,
    ) -> dict[str, Any]:
        enhanced = await self._enhance_with_llm(
            agent_name="CriticAgent",
            result=critic,
            match=match,
            phase=phase,
            context={"prediction": prediction, "narration": narration, "allow_draw": allow_draw},
            output_contract=(
                '返回 {"summary": "...", "passed": true/false, "warnings": ["..."], "errors": ["..."]}。'
                "summary 控制在 30 字以内，通俗说明是否通过；warnings/errors 每条控制在 40 字以内，不得删除规则错误。"
            ),
        )
        rule_errors = self._as_text_list(critic.get("errors"))
        llm_errors = self._as_text_list(enhanced.get("errors"))
        rule_warnings = self._as_text_list(critic.get("warnings"))
        llm_warnings = self._as_text_list(enhanced.get("warnings"))
        # 是否通过只以规则校验为准，避免 LLM 把内部字段或缺失上下文误判成硬错误。
        enhanced["errors"] = rule_errors
        enhanced["warnings"] = list(dict.fromkeys(rule_warnings + llm_warnings + llm_errors))
        enhanced["passed"] = not rule_errors
        enhanced["summary"] = "审核通过。" if enhanced["passed"] else f"发现 {len(rule_errors)} 个关键问题。"
        enhanced["checks"] = critic.get("checks", [])
        enhanced["quality_score"] = critic.get("quality_score")
        return enhanced

    async def predict(
        self,
        match: dict[str, Any],
        teams: list[dict[str, Any]],
        ratings: dict[str, dict[str, Any]],
        allow_draw: bool,
        phase: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """依次执行规划、侦察、分析、模拟、解说和审核。"""

        plan = await self._enhance_plan(self.planner.run(match, ratings), match, ratings, phase)
        await self._emit_agent(plan, match, phase)

        scout = await self._enhance_scout(self.scout.run(match, teams, ratings), match, phase)
        await self._emit_agent(scout, match, phase)
        await self.emit(
            "data_scout_update",
            f"DataScoutAgent 搜索信息：{scout['summary']}",
            phase,
            {
                "match_id": match["match_id"],
                "sources": scout["sources"],
                "search_notes": scout.get("search_notes", []),
                "home": scout["home"],
                "away": scout["away"],
            },
        )

        analysis = await self._enhance_analysis(self.analyst.run(match, ratings, scout), match, ratings, scout, phase)
        await self._emit_agent(analysis, match, phase)

        simulation = self.simulator.run(match, ratings, allow_draw)
        simulation["llm_used"] = False
        simulation["summary"] = f"{simulation['summary']} SimulationAgent 保持固定模拟器，不调用大模型改写比分。"
        await self._emit_agent(simulation, match, phase)
        prediction = simulation["prediction"]

        narration = await self._enhance_narration(self.narrator.run(prediction, analysis), prediction, analysis, match, phase)
        await self._emit_agent(narration, match, phase)

        critic = await self._enhance_critic(
            self.critic.run(
                prediction,
                narration,
                allow_draw,
                match=match,
                scout=scout,
                analysis=analysis,
            ),
            prediction,
            narration,
            match,
            allow_draw,
            phase,
        )
        await self._emit_agent(critic, match, phase)

        prediction["agent_trace"] = [
            {"agent": plan["agent"], "summary": plan["summary"], "plan": plan["plan"], "llm_used": plan.get("llm_used", False)},
            {
                "agent": scout["agent"],
                "summary": scout["summary"],
                "sources": scout["sources"],
                "search_notes": scout.get("search_notes", []),
                "llm_used": scout.get("llm_used", False),
            },
            {
                "agent": analysis["agent"],
                "summary": analysis["summary"],
                "rating_gap": analysis["rating_gap"],
                "factors": analysis["factors"],
                "llm_used": analysis.get("llm_used", False),
            },
            {"agent": simulation["agent"], "summary": simulation["summary"], "llm_used": False},
            {
                "agent": narration["agent"],
                "summary": narration["summary"],
                "text": narration["text"],
                "llm_used": narration.get("llm_used", False),
            },
            {
                "agent": critic["agent"],
                "summary": critic["summary"],
                "passed": critic["passed"],
                "warnings": critic["warnings"],
                "errors": critic["errors"],
                "llm_used": critic.get("llm_used", False),
            },
        ]
        prediction["explanation"] = narration["text"]
        prediction["critic_result"] = critic
        explanation = store_match_explanation(prediction, narration["text"])
        return prediction, explanation
