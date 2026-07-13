import { Button } from "antd";

import { ChampionProb } from "../components/ChampionProb";
import { ReasoningPanel } from "../components/ReasoningPanel";
import { StageAnimation } from "../components/StageAnimation";
import { usePredictionStore } from "../stores/predictionStore";

export function ChampionPage() {
  const startModeRun = usePredictionStore((state) => state.startModeRun);
  return (
    <div className="pageStack">
      <Button type="primary" onClick={() => startModeRun("champion", 1000)}>
        直接进行冠军概率预测
      </Button>
      <div className="twoColumn">
        <ChampionProb />
        <StageAnimation />
      </div>
      <ReasoningPanel />
    </div>
  );
}
