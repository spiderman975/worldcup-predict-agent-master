"""
权限系统 — 三道闸门：硬拒绝 > 规则匹配 > 用户审批
"""

from pathlib import Path
from .config import WORKDIR

# ==================== 闸门 1: 硬拒绝列表 ====================
DENY_LIST = [
    "rm -rf /", "sudo ", "shutdown", "reboot",
    "mkfs", "dd if=", "> /dev/sda", "format ",
    "del /f /s /q", "remove-item -recurse", "rmdir /s",
    "git reset --hard", "git clean -fd",
]


def check_deny_list(command: str) -> str | None:
    for p in DENY_LIST:
        if p in command.lower():
            return f"[拦截] '{p}' 在硬拒绝列表中"
    return None


# ==================== 闸门 2: 规则匹配 ====================

def _is_inside_workdir(path_str: str) -> bool:
    try:
        path = Path(path_str)
        resolved = path.resolve() if path.is_absolute() else (WORKDIR / path).resolve()
        resolved.relative_to(WORKDIR.resolve())
        return True
    except (ValueError, OSError):
        return False


PERMISSION_RULES = [
    {
        "tools": ["write_file", "edit_file"],
        "check": lambda a: not _is_inside_workdir(a.get("path", "")),
        "message": "在工作区外写入文件",
    },
    {
        "tools": ["bash"],
        "check": lambda a: any(k in a.get("command", "") for k in
                               ["rm ", "rm\t", "> /etc/", "chmod 777", "DROP TABLE", "Remove-Item", "del "]),
        "message": "可能具有破坏性的命令",
    },
    {
        "tools": ["bash"],
        "check": lambda a: any(k in a.get("command", "") for k in
                               ["pip install", "npm install", "apt install"]),
        "message": "软件安装命令",
    },
]


def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None


# ==================== 闸门 3: 用户审批 ====================

def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n  [权限] {reason}")
    print(f"  工具: {tool_name}({args})")
    try:
        choice = input("  允许? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "deny"
    return "allow" if choice in ("y", "yes") else "deny"


# ==================== 主管线 ====================

def check_permission(func_name: str, func_args: dict) -> bool:
    """三道闸门串联：硬拒绝 → 规则+审批 → 放行"""
    if func_name == "bash":
        reason = check_deny_list(func_args.get("command", ""))
        if reason:
            print(f"\n  [拒绝] {reason}")
            return False

    reason = check_rules(func_name, func_args)
    if reason:
        if ask_user(func_name, func_args, reason) == "deny":
            return False

    return True
