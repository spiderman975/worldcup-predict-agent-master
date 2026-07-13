"""Register World Cup business tools for the packaged harness."""

from app.harness.my_claude_code.worldcup_workflows import ensure_registered


def register_worldcup_tools() -> None:
    ensure_registered()
