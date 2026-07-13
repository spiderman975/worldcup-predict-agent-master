import json
import hashlib
import math
import re
from pathlib import Path
from typing import Any

class LocalVectorStore:
    """轻量本地向量库。

    MVP 不依赖外部服务，使用哈希词袋向量 + 余弦相似度，把 Agent 生成的
    每场比赛解释持久化到 JSON。后续可以平滑替换为 Chroma、FAISS 或 pgvector。
    """

    def __init__(self, path: Path | None = None, dimensions: int = 256) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / ".local_vector_store" / "match_explanations.json"
        self.dimensions = dimensions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _tokenize(self, text: str) -> list[str]:
        """把中英文混合文本切成可哈希的轻量 token。"""

        latin_tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        cjk_tokens = re.findall(r"[\u4e00-\u9fff]{1,2}", text)
        return latin_tokens + cjk_tokens

    def embed(self, text: str) -> list[float]:
        """生成固定维度的哈希词袋向量。"""

        vector = [0.0] * self.dimensions
        for token in self._tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            vector[int(digest, 16) % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [round(value / norm, 6) for value in vector]

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("[]", encoding="utf-8")
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, item_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """新增或更新一条解释向量。"""

        rows = [row for row in self._load() if row["id"] != item_id]
        row = {"id": item_id, "text": text, "metadata": metadata, "embedding": self.embed(text)}
        rows.append(row)
        self._save(rows)
        return row

    def search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """按余弦相似度检索最相关的比赛解释。"""

        query_vec = self.embed(query)
        results: list[dict[str, Any]] = []
        for row in self._load():
            score = sum(a * b for a, b in zip(query_vec, row["embedding"]))
            results.append(
                {
                    "id": row["id"],
                    "score": round(score, 4),
                    "text": row["text"],
                    "metadata": row["metadata"],
                }
            )
        return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]


match_explanation_store = LocalVectorStore()
