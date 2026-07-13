ALLOWED_AGENT_TOOLS = {
    "football_query.get_all_teams",
    "football_query.get_matches",
    "match_analyze.predict_match",
    "tournament_analyze.simulate_tournament",
}


def is_tool_allowed(tool_name: str) -> bool:
    """工具白名单检查，保证 Agent 初版只能调用项目内已实现的安全工具。"""

    return tool_name in ALLOWED_AGENT_TOOLS
