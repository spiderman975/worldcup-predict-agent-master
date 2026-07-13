# 大模型调用开关说明

当前项目默认保持本地规则预测，不会调用外部 API。

如需测试真实大模型效果，在 `backend/.env` 中配置：

```env
LLM_ENABLED=true
LLM_API_KEY=你的_API_Key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

也可以继续使用旧变量：

```env
LLM_ENABLED=true
QWEN_API_KEY=你的_API_Key
QWEN_MODEL=qwen-plus
```

默认会让以下 Agent 调用大模型增强输出：

```env
LLM_AGENT_NAMES=PlannerAgent,DataScoutAgent,FootballAnalystAgent,NarratorAgent,CriticAgent
```

如果只想测试单场解释文本，可以改成：

```env
LLM_AGENT_NAMES=NarratorAgent,CriticAgent
```

注意：`SimulationAgent` 永远只调用固定 Poisson 模拟器，不让大模型改比分。这样可以保留规则预测作为稳定对照组。
