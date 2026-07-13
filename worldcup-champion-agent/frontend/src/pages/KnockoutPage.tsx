import { Button, Card, Space, Tag } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { AgentPipelineBanner } from "../components/AgentPipelineBanner";
import { KnockoutJourneyBracket } from "../components/KnockoutJourneyBracket";
import { usePredictionStore } from "../stores/predictionStore";

const roundFlow = [
  { key: "quarter", label: "1/4 决赛" },
  { key: "semi", label: "1/2 决赛" },
  { key: "final", label: "决赛" },
];

export function KnockoutPage() {
  const startModeRun = usePredictionStore((state) => state.startModeRun);
  const cancelCurrentRun = usePredictionStore((state) => state.cancelCurrentRun);
  const status = usePredictionStore((state) => state.status);
  const knockoutResults = usePredictionStore((state) => state.knockoutResults);
  const running = status === "running" || status === "pending";
  const [started, setStarted] = useState(false);
  const [visibleRounds, setVisibleRounds] = useState<string[]>([]);
  const [phaseText, setPhaseText] = useState("淘汰赛还未进行");
  const sequencing = useRef(false);
  const hasBracket = useMemo(() => roundFlow.some((round) => Array.isArray(knockoutResults[round.key])), [knockoutResults]);

  const runKnockout = async () => {
    setStarted(true);
    setVisibleRounds([]);
    setPhaseText("正在生成淘汰赛对阵");
    await startModeRun("knockout", 1000, "final");
  };

  const stopPrediction = async () => {
    sequencing.current = false;
    setStarted(false);
    setVisibleRounds([]);
    setPhaseText("淘汰赛还未进行");
    await cancelCurrentRun();
  };

  useEffect(() => {
    if (!started || !hasBracket || sequencing.current) return;
    sequencing.current = true;
    const timers: number[] = [];
    roundFlow.forEach((round, index) => {
      timers.push(window.setTimeout(() => setPhaseText(`正在进行${round.label}`), index * 1800));
      timers.push(
        window.setTimeout(() => {
          setVisibleRounds((current) => [...new Set([...current, round.key])]);
          setPhaseText(`${round.label}已完成`);
        }, index * 1800 + 1100),
      );
    });
    timers.push(window.setTimeout(() => setPhaseText("淘汰赛预测已完成"), roundFlow.length * 1800 + 500));
    return () => timers.forEach(window.clearTimeout);
  }, [hasBracket, started]);

  return (
    <main className="journeyPage">
      <section className="journeyHeader">
        <div>
          <span className="heroKicker">Knockout Bracket</span>
          <h1>淘汰赛预测阶段</h1>
          <p>每轮完成后，胜者会自动填充进下一阶段树状图。点击比分节点可查看 Agent 解释。</p>
        </div>
        <Space wrap>
          {running ? (
            <Button danger size="large" onClick={stopPrediction}>
              停止预测
            </Button>
          ) : (
            <Button type="primary" size="large" onClick={runKnockout}>
              进行淘汰赛阶段
            </Button>
          )}
        </Space>
      </section>
      <AgentPipelineBanner />
      <Card className="glassPanel" title="阶段进程" extra={<Tag color={phaseText.includes("未") ? "default" : "blue"}>{phaseText}</Tag>}>
        <KnockoutJourneyBracket knockoutResults={knockoutResults} visibleRounds={visibleRounds} />
      </Card>
    </main>
  );
}
