import { Card, Steps, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";

const agentOrder = ["PlannerAgent", "DataScoutAgent", "FootballAnalystAgent", "SimulationAgent", "NarratorAgent", "CriticAgent"];
const agentLabels: Record<string, string> = {
  PlannerAgent: "规划",
  DataScoutAgent: "侦察",
  FootballAnalystAgent: "分析",
  SimulationAgent: "模拟",
  NarratorAgent: "解说",
  CriticAgent: "审核",
};

function getDetail(data: Record<string, unknown> | undefined) {
  return (data?.detail ?? {}) as Record<string, unknown>;
}

function shortMessage(message: unknown, maxLen = 88) {
  const text = String(message ?? "").replace(/\s+/g, " ").trim();
  return text.length > maxLen ? `${text.slice(0, maxLen)}...` : text;
}

export function AgentPipelineBanner() {
  const reasoningSteps = usePredictionStore((state) => state.reasoningSteps);
  const latest = [...reasoningSteps]
    .reverse()
    .find((event) => ["agent_node", "data_scout_update", "match_pipeline_start"].includes(event.event));
  const llmEvents = reasoningSteps
    .filter((event) => {
      const message = String(event.message ?? "");
      const detail = getDetail(event.data);
      return Boolean(event.data?.llm_enabled || detail.llm_used || message.includes("大模型"));
    })
    .slice(-3)
    .reverse();
  const latestDetail = getDetail(latest?.data);
  const latestAgent = String(latest?.data?.agent ?? latestDetail.agent ?? "");
  const current = Math.max(0, agentOrder.indexOf(latestAgent));

  return (
    <Card className="agentPipelineBanner">
      <div className="agentPipelineHeader">
        <Tag color="blue">实时 Agent 节点</Tag>
        <span className="agentPipelineMessage">{shortMessage(latest?.message ?? "等待比赛预测节点启动")}</span>
      </div>
      <Steps
        size="small"
        current={current}
        items={[{ title: "规划" }, { title: "侦察" }, { title: "分析" }, { title: "模拟" }, { title: "解说" }, { title: "审核" }]}
      />
      <div className="llmEventLog">
        {llmEvents.length === 0 ? (
          <span className="llmEventEmpty">大模型状态：等待触发。</span>
        ) : (
          llmEvents.map((event, index) => {
            const detail = getDetail(event.data);
            const agent = String(event.data?.agent ?? detail.agent ?? "LLM");
            return (
              <div className="llmEventItem" key={`${event.event}-${index}-${event.message}`}>
                <Tag color={detail.llm_used ? "green" : event.data?.llm_enabled ? "gold" : "default"}>{agentLabels[agent] ?? agent}</Tag>
                <span>{shortMessage(event.message, 72)}</span>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}
