import { Steps } from "antd";

import { usePredictionStore } from "../stores/predictionStore";

const phases = ["DATA_LOADING", "TEAM_RATING", "GROUP_STAGE", "KNOCKOUT", "PROBABILITY", "REASONING", "VERIFY"];
const labels = ["加载数据", "计算评分", "小组赛预测", "淘汰赛模拟", "冠军概率计算", "生成推理", "回审完成"];

export function PredictionProgress() {
  const currentPhase = usePredictionStore((state) => state.currentPhase);
  const current = currentPhase === "COMPLETED" ? phases.length : Math.max(0, phases.indexOf(currentPhase));
  return <Steps size="small" current={current} items={labels.map((title) => ({ title }))} />;
}
