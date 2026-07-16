from typing import Any


class CriticAgent:
    """质量审核员：检查信息完整性、来源可靠性和逻辑一致性。"""

    name = "CriticAgent"

    def run(
        self,
        prediction: dict[str, Any],
        narration: dict[str, Any],
        allow_draw: bool,
        *,
        match: dict[str, Any] | None = None,
        scout: dict[str, Any] | None = None,
        analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        errors: list[str] = []
        checks: list[dict[str, Any]] = []
        home_score = prediction["predicted_home_score"]
        away_score = prediction["predicted_away_score"]

        if not allow_draw and not prediction["winner"]:
            errors.append("淘汰赛预测缺少 winner。")
        if home_score > away_score and prediction["winner"] != prediction["home_team_id"]:
            errors.append("主队比分领先但 winner 不一致。")
        if away_score > home_score and prediction["winner"] != prediction["away_team_id"]:
            errors.append("客队比分领先但 winner 不一致。")
        if prediction["winner_name"] and prediction["winner_name"] not in narration["text"]:
            warnings.append("解释文本没有直接提到胜者名称。")
        if allow_draw and home_score == away_score and prediction["winner"] is not None:
            warnings.append("小组赛平局不应强制 winner。")
        checks.append({"name": "score_winner_consistency", "passed": not errors, "severity": "critical"})

        probability_sum = sum(
            float(prediction.get(key) or 0)
            for key in ("home_win_prob", "draw_prob", "away_win_prob")
        )
        if abs(probability_sum - 1.0) > 0.03:
            errors.append(f"胜平负概率合计为 {probability_sum:.2f}，偏离 1.00。")
        checks.append({"name": "probability_sum", "passed": abs(probability_sum - 1.0) <= 0.03, "severity": "critical"})

        top_scores = prediction.get("top_scores") or []
        if top_scores:
            best = top_scores[0]
            if best.get("home_score") != home_score or best.get("away_score") != away_score:
                warnings.append("预测比分不是 top_scores 中概率最高的比分，请确认模拟器排序或 tie-break 逻辑。")
        else:
            warnings.append("预测结果缺少 top_scores，无法审核比分候选分布。")
        checks.append({"name": "score_distribution_trace", "passed": bool(top_scores), "severity": "major"})

        text = narration.get("text", "")
        home_name = prediction.get("home_team_name", "")
        away_name = prediction.get("away_team_name", "")
        missing_terms = [term for term in (home_name, away_name, str(home_score), str(away_score)) if term and term not in text]
        if missing_terms:
            warnings.append(f"解释文本缺少关键信息：{', '.join(missing_terms[:4])}。")
        if len(text.strip()) < 60:
            warnings.append("解释文本过短，可能无法支撑用户理解预测依据。")
        checks.append({"name": "narration_completeness", "passed": not missing_terms and len(text.strip()) >= 60, "severity": "major"})

        if match:
            required_match_fields = ("match_id", "home_team_id", "away_team_id", "match_time", "stage")
            missing_match_fields = [field for field in required_match_fields if not match.get(field)]
            if missing_match_fields:
                errors.append(f"比赛上下文字段缺失：{', '.join(missing_match_fields)}。")
            if match.get("status") == "finished":
                warnings.append("该比赛数据库状态为已完赛，赛前预测结果需要明确区分真实赛果。")
            checks.append({"name": "match_context_completeness", "passed": not missing_match_fields, "severity": "critical"})

        if scout:
            source_result = self.review_sources(scout.get("source_trace") or {}, scout.get("sources") or [])
            warnings.extend(source_result["warnings"])
            errors.extend(source_result["errors"])
            checks.extend(source_result["checks"])

        if analysis:
            factor_count = len(analysis.get("factors") or [])
            if factor_count < 3:
                warnings.append("分析节点给出的关键因素不足，建议补充攻防、状态、阵容或评分差异。")
            if analysis.get("rating_gap") is None:
                warnings.append("分析节点缺少综合评分差，难以审核强弱判断。")
            checks.append({"name": "analysis_completeness", "passed": factor_count >= 3 and analysis.get("rating_gap") is not None, "severity": "major"})

        return {
            "agent": self.name,
            "summary": "一致性审核通过。" if not errors else "一致性审核发现错误。",
            "passed": not errors,
            "warnings": warnings,
            "errors": errors,
            "checks": checks,
            "quality_score": self._quality_score(errors, warnings),
        }

    def review_sources(self, source_trace: dict[str, Any] | None, fallback_sources: list[Any] | None = None) -> dict[str, Any]:
        """审核网页/数据库来源的可靠性与可追溯性。"""

        warnings: list[str] = []
        errors: list[str] = []
        checks: list[dict[str, Any]] = []
        source_trace = source_trace or {}
        fallback_sources = fallback_sources or []
        source_count = int(source_trace.get("source_count") or len(fallback_sources))
        avg_score = float(source_trace.get("average_credibility") or 0)
        cross_count = int(source_trace.get("cross_validated_count") or 0)
        high_quality_count = int(source_trace.get("high_quality_count") or 0)
        trace_queries = source_trace.get("source_tracing_queries") or []

        if source_count == 0:
            warnings.append("本轮缺少可追溯来源，只能作为离线或本地数据判断。")
        elif avg_score and avg_score < 0.55:
            warnings.append(f"来源平均可信度较低（{avg_score:.2f}），回答应避免绝对化表述。")
        if source_count >= 2 and cross_count == 0:
            warnings.append("搜索结果缺少明显交叉验证，建议继续查官方或权威来源。")
        if source_count > 0 and high_quality_count == 0:
            warnings.append("未发现高可信来源，建议优先追溯官方、权威媒体或体育数据站。")
        if source_count > 0 and not trace_queries:
            warnings.append("缺少来源追溯查询，后续难以定位原始出处。")

        checks.extend(
            [
                {"name": "source_presence", "passed": source_count > 0, "severity": "major"},
                {"name": "source_credibility", "passed": source_count == 0 or avg_score >= 0.55 or avg_score == 0, "severity": "major"},
                {"name": "cross_verification", "passed": source_count < 2 or cross_count > 0, "severity": "major"},
                {"name": "source_traceability", "passed": source_count == 0 or bool(trace_queries), "severity": "minor"},
            ]
        )
        return {
            "agent": self.name,
            "passed": not errors,
            "warnings": warnings,
            "errors": errors,
            "checks": checks,
            "quality_score": self._quality_score(errors, warnings),
        }

    def review_answer(self, answer: str, source_trace: dict[str, Any] | None, *, force_web_search: bool = False) -> dict[str, Any]:
        """审核 Chat 最终回答是否与搜索模式和来源质量匹配。"""

        source_review = self.review_sources(source_trace)
        warnings = list(source_review["warnings"])
        errors = list(source_review["errors"])
        checks = list(source_review["checks"])
        if force_web_search and not (source_trace or {}).get("source_count"):
            warnings.append("用户开启了实时搜索，但最终回答没有可展示网页来源。")
        if force_web_search and "未获得可用网页结果" not in answer and not (source_trace or {}).get("source_count"):
            warnings.append("回答未明确说明实时搜索没有拿到可用网页结果。")
        if any(word in answer for word in ("一定", "必然", "已经确认", "毫无疑问")) and warnings:
            warnings.append("在来源存在不确定性时，最终回答措辞过于绝对。")
        checks.append({"name": "answer_source_alignment", "passed": not warnings, "severity": "major"})
        return {
            "agent": self.name,
            "passed": not errors,
            "warnings": warnings,
            "errors": errors,
            "checks": checks,
            "quality_score": self._quality_score(errors, warnings),
        }

    @staticmethod
    def _quality_score(errors: list[str], warnings: list[str]) -> int:
        return max(1, 10 - len(errors) * 3 - len(warnings))
