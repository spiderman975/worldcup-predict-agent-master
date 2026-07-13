import { Card, Empty, List } from "antd";

import { usePredictionStore } from "../stores/predictionStore";

export function MatchExplanationPanel() {
  const explanations = usePredictionStore((state) => state.matchExplanations);
  return (
    <Card title="每场比赛比分解释" className="panel">
      {explanations.length === 0 ? (
        <Empty description="等待 Agent 逐场生成解释" />
      ) : (
        <List
          size="small"
          dataSource={explanations.slice(-10).reverse()}
          renderItem={(item) => <List.Item>{item.text}</List.Item>}
        />
      )}
    </Card>
  );
}
