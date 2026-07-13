import { Card, Timeline } from "antd";

import { usePredictionStore } from "../stores/predictionStore";

export function StageAnimation() {
  const events = usePredictionStore((state) => state.animationEvents);
  return (
    <Card title="实时可视化动线" className="panel">
      <div className="pulseTrack">
        <span className="pulseDot" />
        <span>Agent 正在按阶段推进预测</span>
      </div>
      <Timeline
        className="compactTimeline"
        items={events.slice(-8).map((event, index) => ({
          key: `${event.message}-${index}`,
          color: index === events.slice(-8).length - 1 ? "green" : "blue",
          children: event.message,
        }))}
      />
    </Card>
  );
}
