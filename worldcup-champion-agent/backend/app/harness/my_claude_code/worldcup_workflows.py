"""World Cup business workflows registered as my-claude-code tools."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .tools import register

_registered = False


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _h_worldcup_get_current_time(timezone_name: str = "Asia/Shanghai") -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        timezone_name = "Asia/Shanghai"
        tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    return _json(
        {
            "timezone": timezone_name,
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": now.strftime("%A"),
            "display_zh": now.strftime("%Y年%m月%d日 %H:%M:%S 北京时间"),
        }
    )


def _h_worldcup_resolve_match(query: str, date_hint: str = "") -> str:
    from app.services.match_prediction_service import resolve_match_query

    return _json(resolve_match_query(query, date_hint=date_hint or None))


def _h_worldcup_get_match_context(match_id: str) -> str:
    from app.services.match_prediction_service import get_match_context

    return _json(get_match_context(match_id))


def _h_worldcup_list_teams() -> str:
    from app.services.data_scout_service import data_scout_service
    from app.services.team_analysis_service import get_team_ratings_and_odds

    ratings = get_team_ratings_and_odds()["team_ratings"]
    return _json(
        [
            {
                "team_id": team["team_id"],
                "name": team["name"],
                "group": team["group"],
                "fifa_rank": team["fifa_rank"],
                "overall_rating": ratings[team["team_id"]]["overall_rating"],
                "attack_strength": ratings[team["team_id"]]["attack_strength"],
                "defense_strength": ratings[team["team_id"]]["defense_strength"],
            }
            for team in data_scout_service.list_teams()
        ]
    )


def _h_worldcup_list_matches(stage: str = "") -> str:
    from app.services.match_prediction_service import list_schedule

    matches = list_schedule()
    filtered = [match for match in matches if not stage or match.get("stage") == stage]
    return _json(
        [
            {
                "match_id": match["match_id"],
                "stage": match["stage"],
                "stage_number": match.get("stage_number"),
                "group": match.get("group"),
                "home_team_id": match["home_team_id"],
                "away_team_id": match["away_team_id"],
                "home_team_name": match["home_team_name"],
                "away_team_name": match["away_team_name"],
                "match_time": match["match_time"],
                "match_date": match["match_date"],
                "venue": match.get("venue"),
                "status": match.get("status"),
                "actual_home_score": match.get("actual_home_score"),
                "actual_away_score": match.get("actual_away_score"),
            }
            for match in filtered
        ]
    )


def _h_worldcup_get_saved_match_prediction(match_id: str) -> str:
    from app.services.match_prediction_service import get_saved_match_prediction

    saved = get_saved_match_prediction(match_id)
    if not saved:
        return _json({"found": False, "message": f"{match_id} 还没有保存的预测结果"})
    return _json({"found": True, "record": saved})


def _h_worldcup_predict_match_workflow(match_id: str, realtime: bool = False) -> str:
    from app.services.match_prediction_service import run_prediction_sync

    return _json(run_prediction_sync(match_id, realtime=realtime))


def _h_worldcup_search_database(query: str, include_web: bool = False, top_k: int = 8) -> str:
    from app.services.data_scout_service import data_scout_service

    return _json(asyncio.run(data_scout_service.search(query, include_web=include_web, top_k=top_k)))


def _h_worldcup_web_search(query: str, purpose: str = "general", top_k: int = 5) -> str:
    from app.services.data_scout_service import data_scout_service

    search_query = f"{query} {purpose}".strip()
    web = asyncio.run(data_scout_service.search_web(search_query, count=top_k))
    return _json({"query": search_query, "purpose": purpose, "web": web, "web_available": bool(web)})


def _h_worldcup_search_match_result(match_id: str, top_k: int = 5) -> str:
    from app.services.match_prediction_service import get_match
    from app.services.data_scout_service import data_scout_service

    match = get_match(match_id)
    if not match:
        return _json({"found": False, "match_id": match_id, "message": "未找到比赛"})
    query = (
        f"{match['home_team_name']} vs {match['away_team_name']} "
        f"{match.get('match_date', '')} final score result World Cup"
    )
    web = asyncio.run(data_scout_service.search_web(query, count=top_k))
    return _json({"found": True, "match": match, "query": query, "web": web, "web_available": bool(web)})


def _h_worldcup_get_team_database_report(team_name: str) -> str:
    from app.services.data_scout_service import data_scout_service

    report = data_scout_service.team_report(team_name)
    if not report:
        return _json({"found": False, "message": f"数据库中没有找到球队：{team_name}"})
    return _json({"found": True, "team": report})


def ensure_registered() -> None:
    global _registered
    if _registered:
        return

    register(
        "worldcup_get_current_time",
        {
            "type": "function",
            "function": {
                "name": "worldcup_get_current_time",
                "description": "获取当前实时北京时间。用户询问现在、今天、赛前赛后、是否完赛时必须调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timezone_name": {"type": "string", "description": "IANA 时区名，默认 Asia/Shanghai。"}
                    },
                    "required": [],
                },
            },
        },
        _h_worldcup_get_current_time,
    )
    register(
        "worldcup_resolve_match",
        {
            "type": "function",
            "function": {
                "name": "worldcup_resolve_match",
                "description": "把自然语言比赛描述解析为赛程中的比赛。支持比赛 ID、球队名、中文别称，如法西大战、法国西班牙、France vs Spain。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "用户原始比赛描述。"},
                        "date_hint": {"type": "string", "description": "可选日期，格式 YYYY-MM-DD。"},
                    },
                    "required": ["query"],
                },
            },
        },
        _h_worldcup_resolve_match,
    )
    register(
        "worldcup_get_match_context",
        {
            "type": "function",
            "function": {
                "name": "worldcup_get_match_context",
                "description": "获取单场比赛上下文，包括赛程、球队、当前北京时间推算状态、数据库状态、真实比分、已保存预测和数据质量警告。",
                "parameters": {
                    "type": "object",
                    "properties": {"match_id": {"type": "string", "description": "比赛 ID。"}},
                    "required": ["match_id"],
                },
            },
        },
        _h_worldcup_get_match_context,
    )
    register(
        "worldcup_list_teams",
        {
            "type": "function",
            "function": {
                "name": "worldcup_list_teams",
                "description": "列出 SQLite 新数据中的世界杯球队、分组、FIFA 排名、综合评分和攻防强度。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        _h_worldcup_list_teams,
    )
    register(
        "worldcup_list_matches",
        {
            "type": "function",
            "function": {
                "name": "worldcup_list_matches",
                "description": "列出 SQLite 新数据中的世界杯赛程，返回北京时间、比赛 ID、状态和真实比分字段。",
                "parameters": {
                    "type": "object",
                    "properties": {"stage": {"type": "string", "description": "比赛阶段，留空返回全部。"}},
                    "required": [],
                },
            },
        },
        _h_worldcup_list_matches,
    )
    register(
        "worldcup_get_saved_match_prediction",
        {
            "type": "function",
            "function": {
                "name": "worldcup_get_saved_match_prediction",
                "description": "读取某场比赛已经保存的单场预测、比分、胜平负概率、理由和 Agent 工作流痕迹。",
                "parameters": {
                    "type": "object",
                    "properties": {"match_id": {"type": "string", "description": "比赛 ID。"}},
                    "required": ["match_id"],
                },
            },
        },
        _h_worldcup_get_saved_match_prediction,
    )
    register(
        "worldcup_predict_match_workflow",
        {
            "type": "function",
            "function": {
                "name": "worldcup_predict_match_workflow",
                "description": "运行并保存单场比赛多 Agent 预测工作流。调用前应先解析比赛并检查是否已完赛。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string", "description": "比赛 ID。"},
                        "realtime": {"type": "boolean", "description": "是否作为赛前实时预测覆盖旧结果。"},
                    },
                    "required": ["match_id"],
                },
            },
        },
        _h_worldcup_predict_match_workflow,
    )
    register(
        "worldcup_search_database",
        {
            "type": "function",
            "function": {
                "name": "worldcup_search_database",
                "description": "搜索 SQLite 世界杯数据库；include_web=true 时也尝试联网搜索，但实时问题更推荐使用 worldcup_web_search。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词。"},
                        "include_web": {"type": "boolean", "description": "是否同时联网搜索，默认 false。"},
                        "top_k": {"type": "integer", "description": "返回条数，默认 8。"},
                    },
                    "required": ["query"],
                },
            },
        },
        _h_worldcup_search_database,
    )
    register(
        "worldcup_web_search",
        {
            "type": "function",
            "function": {
                "name": "worldcup_web_search",
                "description": "明确执行网页搜索。用于最新新闻、伤病、首发、阵容、赔率、实时动态等数据库可能不完整的问题。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "网页搜索关键词。"},
                        "purpose": {"type": "string", "description": "搜索目的，例如 news、injury、lineup、odds、result。"},
                        "top_k": {"type": "integer", "description": "返回条数，默认 5。"},
                    },
                    "required": ["query"],
                },
            },
        },
        _h_worldcup_web_search,
    )
    register(
        "worldcup_search_match_result",
        {
            "type": "function",
            "function": {
                "name": "worldcup_search_match_result",
                "description": "联网搜索某场比赛真实比分和赛果。用于比赛开始 3 小时后、用户询问赛果或数据库比分缺失时。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string", "description": "比赛 ID。"},
                        "top_k": {"type": "integer", "description": "返回条数，默认 5。"},
                    },
                    "required": ["match_id"],
                },
            },
        },
        _h_worldcup_search_match_result,
    )
    register(
        "worldcup_get_team_database_report",
        {
            "type": "function",
            "function": {
                "name": "worldcup_get_team_database_report",
                "description": "读取某支球队在 SQLite 数据库中的阵容、伤病、FIFA 排名、团队攻防和计算摘要。",
                "parameters": {
                    "type": "object",
                    "properties": {"team_name": {"type": "string", "description": "球队英文名或可识别名称。"}},
                    "required": ["team_name"],
                },
            },
        },
        _h_worldcup_get_team_database_report,
    )
    _registered = True


ensure_registered()
