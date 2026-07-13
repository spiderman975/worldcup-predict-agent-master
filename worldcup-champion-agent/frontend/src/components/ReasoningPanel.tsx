import { Alert, Card, Timeline } from "antd";

import { usePredictionStore } from "../stores/predictionStore";

export function ReasoningPanel() {
  const { reasoningSteps, finalReasoning, verifierResult, error } = usePredictionStore();
  return (
    <Card title="Agent 推理过程" className="panel">
      {error ? <Alert type="error" message={error} showIcon /> : null}
      <Timeline
        items={reasoningSteps.slice(-12).map((step, index) => ({
          key: `${step.event}-${index}`,
          color: step.event === "prediction_error" ? "red" : step.event === "prediction_complete" ? "green" : "blue",
          children: `${step.phase ?? step.event}：${step.message}`,
        }))}
      />
      {finalReasoning ? <Alert type="info" message="最终推理" description={finalReasoning} showIcon /> : null}
      {verifierResult ? (
        <Alert
          className="verifyBox"
          type={verifierResult.passed ? "success" : "warning"}
          message={verifierResult.passed ? "Verifier 通过" : "Verifier 发现问题"}
          description={[...verifierResult.warnings, ...verifierResult.errors].join("；") || "预测结果与推理文本一致。"}
          showIcon
        />
      ) : null}
    </Card>
  );
}
