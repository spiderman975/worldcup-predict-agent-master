import json
import logging

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)


def _collect_facts(
    champion_id: str,
    champion_probabilities: list[dict],
    group_results: dict,
    knockout_results: dict,
    ratings: dict,
) -> dict:
    """把结构化预测结果整理成事实字典，供模板或 LLM 使用。"""

    champion = ratings[champion_id]
    probability = next(
        (item["probability"] for item in champion_probabilities if item["team_id"] == champion_id),
        0,
    )
    final_match = knockout_results.get("final", [{}])[0]
    group_rows: list[dict] = []
    for rows in group_results.get("group_tables", {}).values():
        group_rows.extend(rows)
    champion_group_row = next((row for row in group_rows if row["team_id"] == champion_id), {})
    return {
        "champion_name": champion["name"],
        "champion_probability": probability,
        "overall_rating": champion["overall_rating"],
        "attack_strength": champion["attack_strength"],
        "defense_strength": champion["defense_strength"],
        "form_score": champion["form_score"],
        "group_points": champion_group_row.get("points", "N/A"),
        "goal_difference": champion_group_row.get("goal_difference", "N/A"),
        "top_probabilities": champion_probabilities[:5],
        "final_match": {
            "home_team_name": final_match.get("home_team_name"),
            "away_team_name": final_match.get("away_team_name"),
            "predicted_home_score": final_match.get("predicted_home_score"),
            "predicted_away_score": final_match.get("predicted_away_score"),
            "winner_name": final_match.get("winner_name"),
        },
    }


def _build_template_reasoning(facts: dict, provider_note: str) -> str:
    """本地模板解释，保证离线或 API 失败时仍可用。"""

    final_match = facts["final_match"]
    return (
        f"{provider_note}\n"
        f"最终预测冠军是 {facts['champion_name']}，Monte Carlo 冠军概率为 {facts['champion_probability']:.1%}。"
        f"它的综合评分为 {facts['overall_rating']:.2f}，攻击强度 {facts['attack_strength']:.2f}，"
        f"防守强度 {facts['defense_strength']:.2f}，近期状态 {facts['form_score']:.2f}。\n"
        f"小组赛阶段，{facts['champion_name']} 积分 {facts['group_points']}，"
        f"净胜球 {facts['goal_difference']}，体现了稳定的出线能力。"
        f"决赛预测为 {final_match['home_team_name']} {final_match['predicted_home_score']}"
        f"-{final_match['predicted_away_score']} {final_match['away_team_name']}，"
        f"胜者为 {final_match['winner_name']}。"
        "需要注意的是，初版使用 16 队 demo 数据和简化赛程，概率用于展示 Agent 决策链路，不代表真实投注建议。"
    )


def _friendly_llm_error(exc: Exception) -> str:
    text = str(exc)
    if "10061" in text or "actively refused" in text or "积极拒绝" in text:
        return (
            "无法连接 Qwen/DashScope：检测到本地代理端口拒绝连接。"
            "常见原因是 VPN/代理已关闭，但 HTTP_PROXY/HTTPS_PROXY 仍指向本地代理。"
        )
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)) or "timed out" in text.lower() or "timeout" in text.lower():
        return "无法连接 Qwen/DashScope：当前网络直连超时，请检查网络是否能访问 dashscope.aliyuncs.com。"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "Qwen/DashScope 鉴权失败：请检查 API Key 是否正确、是否有模型调用权限。"
        return f"Qwen/DashScope 返回 HTTP {status}，已回退本地模板。"
    return f"Qwen/DashScope 调用失败：{text}"


def _call_qwen(facts: dict, api_key: str) -> str:
    """调用 DashScope Qwen（OpenAI 兼容接口）生成中文推理解释。"""

    settings = get_settings()
    system_prompt = (
        "你是一名足球赛事分析师。请严格根据提供的结构化预测数据撰写中文解释，"
        "不得编造数据或引入未给出的信息。必须明确提到冠军球队的名称，"
        "语言专业、条理清晰，控制在 200 字以内，并说明这是基于 demo 数据的展示性预测。"
    )
    user_prompt = (
        "以下是本次世界杯冠军预测的结构化结果（JSON）：\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n"
        "请据此生成一段解释冠军预测理由的中文分析。"
    )
    response = httpx.post(
        f"{settings.dashscope_base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.qwen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
        },
        timeout=settings.llm_timeout_seconds,
        trust_env=False,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    if not content:
        raise ValueError("LLM 返回空内容")
    if facts["champion_name"] not in content:
        content = f"最终预测冠军：{facts['champion_name']}。\n{content}"
    return content


def generate_reasoning(
    champion_id: str,
    champion_probabilities: list[dict],
    group_results: dict,
    knockout_results: dict,
    ratings: dict,
) -> str:
    """生成冠军预测解释；配置 Qwen/DashScope Key 时调用远程模型，否则使用本地模板。"""

    settings = get_settings()
    facts = _collect_facts(champion_id, champion_probabilities, group_results, knockout_results, ratings)
    api_key = settings.dashscope_api_key or settings.qwen_api_key
    if api_key:
        try:
            return _call_qwen(facts, api_key)
        except Exception as exc:  # noqa: BLE001 - 远程失败时回退本地模板，保证任务不中断
            logger.warning("Qwen 推理调用失败，回退本地模板：%s", exc)
            return _build_template_reasoning(
                facts, f"{_friendly_llm_error(exc)} 本次回退本地模板生成解释。"
            )
    return _build_template_reasoning(facts, "未配置 Qwen/DashScope Key，本次使用本地模板生成解释。")
