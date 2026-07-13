TEAM_ALIASES = {
    "Brasil": "Brazil",
    "Korea Republic": "South Korea",
    "United States": "USA",
}


def normalize_team_name(name: str) -> str:
    """统一球队名称，后续接外部数据源时可在这里扩展别名映射。"""

    clean_name = name.strip()
    return TEAM_ALIASES.get(clean_name, clean_name)
