import json
from typing import Any

import httpx

from app.core.config import get_settings


class LLMService:
    """大模型调用服务。

    这里使用 OpenAI-compatible 的 `/chat/completions` 协议，默认适配阿里云
    DashScope 兼容模式；如果没有显式开启或没有 API Key，则保持离线规则模式。
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        """判断当前是否允许真实调用大模型。"""

        return bool(self.settings.llm_enabled and self.settings.llm_api_key)

    def agent_enabled(self, agent_name: str) -> bool:
        """判断某个 Agent 是否启用 LLM 增强。"""

        return self.enabled and agent_name in self.settings.llm_agent_names

    @staticmethod
    def describe_error(exc: Exception) -> str:
        """Turn low-level network/client exceptions into user-facing diagnostics."""

        text = str(exc)
        if "10061" in text or "actively refused" in text or "积极拒绝" in text:
            return "本地代理端口拒绝连接。请检查 VPN/代理是否已关闭但 HTTP_PROXY/HTTPS_PROXY 仍指向本地代理。"
        if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)) or "timed out" in text.lower() or "timeout" in text.lower():
            return "连接 DashScope 超时。请确认当前网络能访问 dashscope.aliyuncs.com，或配置可用代理。"
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in {401, 403}:
                return "DashScope 鉴权失败。请检查 API Key、模型名和调用权限。"
            return f"DashScope 返回 HTTP {status}。"
        return text

    async def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI-compatible Chat Completions，并返回文本内容。"""

        if not self.enabled:
            raise RuntimeError("LLM 未启用，请配置 LLM_ENABLED=true 和 API Key。")

        url = f"{self.settings.llm_base_url}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        # Do not inherit OS proxy variables by default. Local VPN/proxy tools often
        # leave HTTP_PROXY/HTTPS_PROXY pointing at a closed 127.0.0.1 port.
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        return str(data["choices"][0]["message"]["content"]).strip()

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """调用大模型并解析 JSON，便于 Agent 返回结构化增强结果。"""

        text = await self.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._parse_json_object(text)

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        """尽量从模型输出中抽取一个 JSON 对象。"""

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else {"text": str(value)}
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                value = json.loads(cleaned[start : end + 1])
                return value if isinstance(value, dict) else {"text": str(value)}
            return {"text": cleaned}


llm_service = LLMService()
