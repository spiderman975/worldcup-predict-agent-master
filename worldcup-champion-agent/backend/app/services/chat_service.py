"""Chat sessions and deterministic World Cup intent routing."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any, AsyncGenerator, Literal
from zoneinfo import ZoneInfo

from app.services.llm_service import llm_service
from app.services.match_prediction_service import (
    find_match_from_text,
    get_saved_match_prediction,
    list_schedule,
    predict_single_match,
)
from app.services.my_claude_runtime_service import my_claude_runtime_service
from app.services.stream_service import stream_service
from app.services.team_analysis_service import get_team_ratings_and_odds, search_teams

logger = logging.getLogger(__name__)

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
TERMINAL_EVENTS = {"prediction_complete", "prediction_error", "prediction_canceled"}


class ChatSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.messages: list[dict[str, str]] = []
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.created_at = datetime.now(BEIJING_TZ)
        self.active_task: asyncio.Task[None] | None = None
        self.run_id: str | None = None


_sessions: dict[str, ChatSession] = {}


def _now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ)


def _message_time() -> str:
    return _now_beijing().isoformat()


def create_session() -> ChatSession:
    session_id = str(uuid.uuid4())
    session = ChatSession(session_id)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)


async def _put_message(session: ChatSession, role: str, content: str, **extra: Any) -> None:
    await session.queue.put(
        {
            "event": f"{role}_message",
            "data": {"role": role, "content": content, "timestamp": _message_time(), **extra},
        }
    )


async def _stream_agent_message(session: ChatSession, content: str, **extra: Any) -> None:
    timestamp = _message_time()
    for token in content:
        await session.queue.put(
            {"event": "agent_token", "data": {"role": "agent", "token": token, "timestamp": timestamp, **extra}}
        )
        await asyncio.sleep(0.012)
    await session.queue.put(
        {"event": "agent_done", "data": {"role": "agent", "content": content, "timestamp": timestamp, **extra}}
    )


async def _stream_with_llm(session: ChatSession) -> str:
    if my_claude_runtime_service.enabled:
        answer = ""
        timestamp = _message_time()
        contextual_messages = [
            {
                "role": "system",
                "content": f"当前北京时间是 {_format_beijing_datetime(_now_beijing())}。涉及今天、现在、赛前赛后时必须以这个时间为准。",
            },
            *session.messages,
        ]
        async for token in my_claude_runtime_service.stream(contextual_messages):
            answer += token
            await session.queue.put(
                {"event": "agent_token", "data": {"role": "agent", "token": token, "timestamp": timestamp}}
            )
        await session.queue.put(
            {"event": "agent_done", "data": {"role": "agent", "content": answer, "timestamp": timestamp}}
        )
        return answer

    return await _answer_with_llm(session)


Intent = Literal["identity", "full_prediction", "single_predict", "saved_prediction", "schedule", "team", "time", "general"]


def _classify(message: str) -> Intent:
    text = message.lower().strip()
    if any(word in text for word in ["你是谁", "你能做什么", "怎么用", "who are you", "help"]):
        return "identity"
    if any(word in text for word in ["现在几点", "当前时间", "今天日期", "北京时间", "实时时间"]):
        return "time"
    if any(word in text for word in ["完整预测", "冠军预测", "预测冠军", "全量模拟", "完整模拟", "champion"]):
        return "full_prediction"
    if any(word in text for word in ["已预测", "预测结果", "保存", "理由", "为什么", "比分及理由", "结果"]):
        return "saved_prediction"
    if any(word in text for word in ["赛程", "日程", "时间", "哪天", "比赛日", "比赛安排", "今日比赛", "今天比赛", "schedule"]):
        return "schedule"
    if any(word in text for word in ["预测", "胜负", "输赢", "比分", "谁赢", "predict", "vs", "对阵"]):
        return "single_predict"
    if any(word in text for word in ["球队", "评分", "实力", "攻防", "排名", "分组", "team"]):
        return "team"
    return "general"


def _format_beijing_datetime(value: datetime) -> str:
    return value.astimezone(BEIJING_TZ).strftime("%Y年%m月%d日 %H:%M:%S 北京时间")


def _extract_schedule_date(message: str, now: datetime | None = None) -> date | None:
    current = now or _now_beijing()
    text = message.strip()
    if "今天" in text or "今日" in text:
        return current.date()
    if "明天" in text:
        return current.date() + timedelta(days=1)
    if "后天" in text:
        return current.date() + timedelta(days=2)
    if "昨天" in text:
        return current.date() - timedelta(days=1)

    iso_match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        return date(year, month, day)

    month_day_match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)
    if month_day_match:
        month, day = map(int, month_day_match.groups())
        return date(current.year, month, day)

    return None


def _format_match_line(match: dict[str, Any]) -> str:
    status = "已完赛" if match.get("status") == "finished" else "未赛"
    score = ""
    if match.get("status") == "finished":
        score = f"，比分 {match.get('actual_home_score')}-{match.get('actual_away_score')}"
    return (
        f"- {match['match_time'][11:19]} 北京时间，{match['match_id']}："
        f"{match['home_team_name']} vs {match['away_team_name']}，{status}{score}"
    )


def _format_prediction(record: dict[str, Any], prefix: str = "预测完成") -> str:
    prediction = record["prediction"]
    match = record["match"]
    winner = prediction.get("winner_name") or "平局"
    score = f"{prediction['predicted_home_score']}-{prediction['predicted_away_score']}"
    trace = prediction.get("agent_trace") or []
    trace_text = "；".join(str(item.get("summary", "")) for item in trace[:3] if item.get("summary"))
    return (
        f"{prefix}：{match['home_team_name']} vs {match['away_team_name']}，模型倾向 {winner}，预测比分 {score}。\n"
        f"胜平负概率：主胜 {prediction['home_win_prob']:.1%}，平局 {prediction['draw_prob']:.1%}，客胜 {prediction['away_win_prob']:.1%}。\n"
        f"理由：{prediction.get('explanation') or record.get('explanation', {}).get('text', '暂无解释文本')}\n"
        f"工作流摘要：{trace_text or '已完成单场多 Agent 工作流。'}"
    )


def _answer_identity() -> str:
    return (
        "我是这个项目里的 WorldCup Chat Agent，属于 my-claude-code 主系统的网页入口。\n"
        "我可以查 SQLite 新数据里的球队、赛程、阵容、伤病、已保存单场预测，也可以按比赛 ID 或双方球队触发单场多 Agent 预测。\n"
        "涉及今天、现在、赛前赛后时，我会使用北京时间精确到秒。"
    )


def _answer_time() -> str:
    return f"当前时间是 {_format_beijing_datetime(_now_beijing())}。"


def _answer_schedule(message: str) -> str:
    now = _now_beijing()
    target_date = _extract_schedule_date(message, now)
    matches = list_schedule()

    if target_date:
        date_text = target_date.isoformat()
        day_matches = [match for match in matches if match["match_date"] == date_text]
        heading = f"当前北京时间：{_format_beijing_datetime(now)}。\n你查询的是 {date_text} 的比赛安排。"
        if not day_matches:
            return f"{heading}\n这一天数据库中没有赛程。"
        return f"{heading}\n共有 {len(day_matches)} 场：\n" + "\n".join(_format_match_line(match) for match in day_matches)

    lines = [_format_match_line(match) for match in matches[:12]]
    return (
        f"当前北京时间：{_format_beijing_datetime(now)}。\n"
        "你没有指定日期，我先列出最近 12 场赛程；也可以问“今天比赛安排”或“7月14日比赛安排”。\n"
        + "\n".join(lines)
    )


def _answer_team(message: str) -> str:
    hits = search_teams(message)[:5]
    ratings = get_team_ratings_and_odds()["team_ratings"]
    if not hits:
        top = sorted(ratings.values(), key=lambda item: item["overall_rating"], reverse=True)[:6]
        return "你可以问某支球队的攻防实力。当前综合评分靠前的是：\n" + "\n".join(
            f"{item['name']}：综合 {item['overall_rating']:.2f}，进攻 {item['attack_strength']:.2f}，防守 {item['defense_strength']:.2f}"
            for item in top
        )
    return "我查到这些球队：\n" + "\n".join(
        f"{team['name']}：{team['group']} 组，FIFA 排名 {team['fifa_rank']}，进攻 {team['attack_score']:.2f}，防守 {team['defense_score']:.2f}"
        for team in hits
    )


async def _answer_saved_prediction(user_message: str) -> str:
    match = find_match_from_text(user_message)
    if not match:
        return "你想查哪一场已经保存的预测？可以直接说双方球队，例如 France vs Spain。"
    saved = get_saved_match_prediction(match["match_id"])
    if not saved:
        return f"{match['match_id']}（{match['home_team_name']} vs {match['away_team_name']}）还没有保存的预测结果。你可以说“预测 {match['match_id']} 比分”来生成。"
    return _format_prediction(saved, prefix="已保存预测")


async def _answer_single_prediction(user_message: str) -> str:
    match = find_match_from_text(user_message)
    if not match:
        return "我需要先确定比赛。请给我比赛 ID，或写成 `France vs Spain` 这种双方球队格式。"
    record = await predict_single_match(match["match_id"], realtime=False)
    return _format_prediction(record)


async def _answer_with_llm(session: ChatSession) -> str:
    system_prompt = f"你是 worldcup-predict-agent 的中文聊天 Agent。当前北京时间是 {_format_beijing_datetime(_now_beijing())}。"
    user_prompt = session.messages[-1]["content"]
    if llm_service.enabled:
        return await llm_service.complete(system_prompt=system_prompt, user_prompt=user_prompt)
    return _answer_identity()


async def send_message(session_id: str, user_message: str) -> None:
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Chat session {session_id} does not exist")

    session.messages.append({"role": "user", "content": user_message})
    await _put_message(session, "user", user_message)

    if session.active_task and not session.active_task.done():
        await _put_message(session, "system", "上一条请求仍在处理，请稍后再试。")
        return

    session.active_task = asyncio.create_task(_run_chat_turn(session, user_message))


async def _run_chat_turn(session: ChatSession, user_message: str) -> None:
    try:
        await session.queue.put(
            {
                "event": "agent_status",
                "data": {"message": "Agent 正在分析问题...", "timestamp": _message_time()},
            }
        )
        intent = _classify(user_message)
        if intent in {"single_predict", "saved_prediction"} and my_claude_runtime_service.enabled:
            answer = await _stream_with_llm(session)
            session.messages.append({"role": "assistant", "content": answer})
            return
        if intent == "identity":
            answer = _answer_identity()
        elif intent == "time":
            answer = _answer_time()
        elif intent == "full_prediction":
            answer = "整届赛事预测仍依赖旧 demo 赛制规则，当前已停用。现在保留的是 SQLite 新数据的赛程查询、球队查询和单场预测。"
        elif intent == "single_predict":
            answer = await _answer_single_prediction(user_message)
        elif intent == "saved_prediction":
            answer = await _answer_saved_prediction(user_message)
        elif intent == "schedule":
            answer = _answer_schedule(user_message)
        elif intent == "team":
            answer = _answer_team(user_message)
        else:
            answer = await _stream_with_llm(session)
            session.messages.append({"role": "assistant", "content": answer})
            return

        session.messages.append({"role": "assistant", "content": answer})
        await _stream_agent_message(session, answer)
    except Exception as exc:
        logger.exception("Chat turn failed")
        await session.queue.put({"event": "agent_error", "data": {"error": llm_service.describe_error(exc)}})


async def start_prediction_from_chat(session_id: str, monte_carlo_runs: int = 1000) -> str:
    session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Chat session {session_id} does not exist")
    await _put_message(session, "system", "整届赛事预测仍依赖旧 demo 赛制规则，当前已停用。请使用单场预测。")
    raise RuntimeError("旧 demo 整届预测已停用")


async def _relay_prediction_events(session: ChatSession, run_id: str) -> None:
    queue = stream_service.subscribe(run_id)
    try:
        while True:
            payload = await queue.get()
            event_name = payload.get("event", "message")
            await session.queue.put({"event": event_name, "data": payload})
            if event_name in TERMINAL_EVENTS:
                if event_name == "prediction_complete":
                    final_reasoning = payload.get("data", {}).get("final_reasoning")
                    if final_reasoning:
                        await _stream_agent_message(session, str(final_reasoning), run_id=run_id)
                break
    finally:
        stream_service.unsubscribe(run_id, queue)


async def stream_session(session_id: str) -> AsyncGenerator[dict[str, str], None]:
    session = _sessions.get(session_id)
    if not session:
        return

    while True:
        try:
            payload = await asyncio.wait_for(session.queue.get(), timeout=300)
            yield {
                "event": payload.get("event", "message"),
                "data": json.dumps(payload.get("data", {}), ensure_ascii=False),
            }
        except asyncio.TimeoutError:
            yield {"event": "heartbeat", "data": "{}"}
