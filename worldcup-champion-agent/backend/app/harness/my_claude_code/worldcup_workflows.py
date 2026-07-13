"""World Cup business workflows registered as my-claude-code tools."""

from __future__ import annotations

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
    import asyncio

    from app.services.data_scout_service import data_scout_service

    return _json(asyncio.run(data_scout_service.search(query, include_web=include_web, top_k=top_k)))


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
                "description": "获取当前实时时间。用户询问现在几点、今天日期、北京时间、赛前赛后状态时必须调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timezone_name": {
                            "type": "string",
                            "description": "IANA 时区名称，默认 Asia/Shanghai。",
                        }
                    },
                    "required": [],
                },
            },
        },
        _h_worldcup_get_current_time,
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
                    "properties": {
                        "stage": {"type": "string", "description": "比赛阶段，例如 group、quarter、semi、final；留空返回全部。"}
                    },
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
                    "properties": {"match_id": {"type": "string", "description": "比赛 ID，例如 s1_mexico_south_africa。"}},
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
                "description": "运行并保存单场比赛多 Agent 预测工作流。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string", "description": "比赛 ID，例如 s4_france_spain。"},
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
                "description": "搜索 SQLite 世界杯数据库；include_web=true 时尝试联网搜索，需要 BOCHA_API_KEY。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词，例如 Brazil 伤病、Mexico lineup、s4_france_spain。"},
                        "include_web": {"type": "boolean", "description": "是否同时尝试联网搜索，默认 false。"},
                        "top_k": {"type": "integer", "description": "返回条数，默认 8。"},
                    },
                    "required": ["query"],
                },
            },
        },
        _h_worldcup_search_database,
    )
    register(
        "worldcup_get_team_database_report",
        {
            "type": "function",
            "function": {
                "name": "worldcup_get_team_database_report",
                "description": "读取某支球队在 SQLite 数据库中的阵容、伤病、FIFA 排名、团队攻防和计算攻防摘要。",
                "parameters": {
                    "type": "object",
                    "properties": {"team_name": {"type": "string", "description": "球队英文名，例如 Brazil、Mexico。"}},
                    "required": ["team_name"],
                },
            },
        },
        _h_worldcup_get_team_database_report,
    )
    _registered = True


ensure_registered()
