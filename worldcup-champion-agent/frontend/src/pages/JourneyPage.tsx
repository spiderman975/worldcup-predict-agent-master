import { Button, message } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getTeams } from "../api/predictionApi";
import { GroupDrawBoard } from "../components/GroupDrawBoard";
import { usePredictionStore } from "../stores/predictionStore";
import type { Team } from "../types/prediction";

export function JourneyPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [starting, setStarting] = useState(false);
  const startGroupRoundRun = usePredictionStore((state) => state.startGroupRoundRun);
  const cancelCurrentRun = usePredictionStore((state) => state.cancelCurrentRun);
  const status = usePredictionStore((state) => state.status);
  const navigate = useNavigate();
  const running = status === "running" || status === "pending";

  useEffect(() => {
    getTeams().then(setTeams).catch(() => message.error("球队数据加载失败"));
  }, []);

  const startGroupStage = async () => {
    setStarting(true);
    await startGroupRoundRun(1, 1000);
    navigate("/group?round=1");
  };

  const stopPrediction = async () => {
    setStarting(false);
    await cancelCurrentRun();
  };

  return (
    <main className="journeyPage">
      <section className="journeyHeader">
        <div>
          <span className="heroKicker">Group Draw</span>
          <h1>世界杯小组赛分组</h1>
          <p>背景图层将在预测旅程中保持，所有结果都会叠加在世界杯主题舞台上。</p>
        </div>
        {running ? (
          <Button size="large" danger onClick={stopPrediction}>
            停止预测
          </Button>
        ) : (
          <Button size="large" type="primary" loading={starting} onClick={startGroupStage}>
            小组赛开赛
          </Button>
        )}
      </section>
      <GroupDrawBoard teams={teams} />
    </main>
  );
}
