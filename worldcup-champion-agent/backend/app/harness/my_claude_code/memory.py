"""
Memory — 文件系统持久化记忆
存储 / 加载 / 提取 / 整理 四个子系统
适配 OpenAI API
"""

import json, re
from datetime import datetime
from pathlib import Path
from .config import MODEL, MEMORY_DIR, CONSOLIDATE_THRESHOLD

MEMORY_TYPES = ["user", "feedback", "project", "reference"]
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"


# ==================== 存储 ====================

def write_memory(name: str, mem_type: str, description: str, body: str) -> None:
    if mem_type not in MEMORY_TYPES:
        mem_type = "project"
    slug = re.sub(r'[^a-z0-9-]', '-', name.lower().strip())
    fp = MEMORY_DIR / f"{slug}.md"
    fp.write_text(
        f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n"
        f"created: {datetime.now().isoformat()}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    _rebuild_index()


def _rebuild_index():
    files = list_memories()
    if not files:
        MEMORY_INDEX.unlink(missing_ok=True)
        return
    lines = ["# Memory Index\n"]
    for f in files:
        lines.append(f"- **{f['name']}** [{f['type']}]: {f['description']}")
    MEMORY_INDEX.write_text("\n".join(lines), encoding="utf-8")


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def list_memories() -> list[dict]:
    results = []
    if not MEMORY_DIR.exists():
        return results
    for fp in sorted(MEMORY_DIR.glob("*.md")):
        if fp.name == "MEMORY.md":
            continue
        try:
            meta = _parse_frontmatter(fp.read_text(encoding="utf-8"))
            results.append({
                "name": meta.get("name", fp.stem),
                "description": meta.get("description", ""),
                "type": meta.get("type", "project"),
                "path": str(fp),
            })
        except Exception:
            continue
    return results


# ==================== 加载 ====================

def load_index() -> str:
    """读取索引内容，注入 system prompt"""
    return MEMORY_INDEX.read_text(encoding="utf-8").strip() if MEMORY_INDEX.exists() else ""


def read_memory(name: str) -> str:
    slug = re.sub(r'[^a-z0-9-]', '-', name.lower().strip())
    fp = MEMORY_DIR / f"{slug}.md"
    if not fp.exists():
        return ""
    text = fp.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else text
    return text


def select_relevant(messages: list, client, max_items: int = 5) -> list[str]:
    """LLM side-query 选相关记忆，返回文件内容列表"""
    files = list_memories()
    if not files:
        return []
    catalog = "\n".join(f"{i}: {f['name']} [{f['type']}] — {f['description']}" for i, f in enumerate(files))
    recent = json.dumps(messages[-6:], ensure_ascii=False)[:2000]
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "只返回一个整数 JSON 数组，不要解释。"},
                {"role": "user", "content":
                 f"最近对话:\n{recent}\n\n记忆目录:\n{catalog}\n\n相关记忆编号（最多 {max_items} 条）:"},
            ],
            max_tokens=200,
        )
        text = resp.choices[0].message.content or ""
        m = re.search(r'\[.*?\]', text)
        if m:
            indices = json.loads(m.group())
            return [read_memory(files[i]["name"]) for i in indices[:max_items] if 0 <= i < len(files)]
    except Exception:
        pass
    return []


# ==================== 提取 ====================

def extract_memories(messages: list, client) -> None:
    """每轮结束时自动提取值得记住的信息"""
    existing = {f["name"].lower() for f in list_memories()}
    recent = json.dumps(messages[-10:], ensure_ascii=False)[:4000]
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content":
                 "提取值得记住的信息。返回 JSON 数组，每项包含 "
                 "{name, type, description, body}。没有则返回空数组 []。"},
                {"role": "user", "content": recent},
            ],
            max_tokens=1000,
        )
        text = resp.choices[0].message.content or ""
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            for item in json.loads(m.group()):
                name = item.get("name", "").strip()
                if name and name.lower() not in existing:
                    write_memory(name, item.get("type", "project"), item.get("description", ""), item.get("body", ""))
                    existing.add(name.lower())
    except Exception:
        pass


# ==================== 整理 ====================

def consolidate(client) -> None:
    """文件达阈值时 LLM 去重合并"""
    files = list_memories()
    if len(files) < CONSOLIDATE_THRESHOLD:
        return
    all_mems = [{"name": f["name"], "type": f["type"], "description": f["description"],
                 "body": read_memory(f["name"])} for f in files]
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content":
                 "合并去重、解决矛盾。"
                 "返回 JSON 数组，每项包含 {name, type, description, body}。"},
                {"role": "user", "content": json.dumps(all_mems, ensure_ascii=False)},
            ],
            max_tokens=4000,
        )
        text = resp.choices[0].message.content or ""
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            for f in files:
                Path(f["path"]).unlink(missing_ok=True)
            for item in json.loads(m.group()):
                write_memory(item.get("name", "memory"), item.get("type", "project"),
                             item.get("description", ""), item.get("body", ""))
    except Exception:
        pass
