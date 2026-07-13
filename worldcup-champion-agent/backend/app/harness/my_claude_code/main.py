"""
My-Claude-Code — 入口
20 个 Harness 机制，一个不变的循环
"""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = "app.harness.my_claude_code"
    from app.harness.my_claude_code.hooks import register_hook, clear_hooks
    from app.harness.my_claude_code.planner import h_list_tasks, start_scheduler, stop_scheduler
    from app.harness.my_claude_code.mcp import disconnect_all
    from app.harness.my_claude_code import worldcup_workflows  # noqa: F401
else:
    from .hooks import register_hook, clear_hooks
    from .planner import h_list_tasks, start_scheduler, stop_scheduler
    from .mcp import disconnect_all
    from . import worldcup_workflows  # noqa: F401


def setup_hooks():
    """注册示例 Hook"""
    def log_tool(func_name, func_args):
        print(f"  [>] {func_name}")
    register_hook("PreToolUse", log_tool)


def main():
    # 初始化 OpenAI 客户端
    try:
        from openai import OpenAI
    except ImportError:
        print("pip install openai")
        sys.exit(1)

    from .config import LLM_API_KEY, LLM_BASE_URL, MODEL, WORKDIR
    if not LLM_API_KEY:
        print("未配置 LLM_API_KEY / QWEN_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY")
        print("可在 backend/.env 中配置，或在当前终端设置环境变量。")
        sys.exit(1)
    import httpx
    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        http_client=httpx.Client(trust_env=False),
    )

    print("=" * 50)
    print("  My-Claude-Code — 智能体框架")
    print("  模型:", end=" ")
    print(MODEL)
    print("  工作目录:", WORKDIR)
    print("  /compact  /memory  /tasks  /clear  /quit")
    print("=" * 50)

    setup_hooks()
    start_scheduler()
    messages = []

    try:
        while True:
            try:
                user_input = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "/quit"):
                print("再见！")
                break

            # 斜杠命令
            if user_input.startswith("/"):
                if user_input == "/compact":
                    from .context import run_compaction
                    messages = run_compaction(messages, client)
                    print("[已压缩]")
                    continue
                elif user_input == "/memory":
                    from .memory import list_memories
                    for m in list_memories():
                        print(f"  [{m['type']}] {m['name']}: {m['description']}")
                    if not list_memories():
                        print("  (暂无记忆)")
                    continue
                elif user_input == "/tasks":
                    print(h_list_tasks())
                    continue
                elif user_input == "/clear":
                    messages = []
                    print("[已清空]")
                    continue

            # 正常对话
            messages.append({"role": "user", "content": user_input})
            try:
                from .agent import enhanced_loop
                result = enhanced_loop(messages, client)
                if result:
                    print(f"\n{result}")
            except KeyboardInterrupt:
                print("\n[已中断]")
                if messages and messages[-1]["role"] == "user":
                    messages.pop()
    finally:
        stop_scheduler()
        disconnect_all()
        clear_hooks()


if __name__ == "__main__":
    main()
