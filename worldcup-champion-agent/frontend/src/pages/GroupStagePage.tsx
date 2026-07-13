import { Button, Card, Space, Table, Tag } from "antd";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { AgentPipelineBanner } from "../components/AgentPipelineBanner";
import { GroupThirdRanking } from "../components/GroupThirdRanking";
import { RoundMatchBoard } from "../components/RoundMatchBoard";
import { usePredictionStore } from "../stores/predictionStore";
import type { GroupRow } from "../types/prediction";
import { getGroupMatchesByRound } from "../utils/groupRounds";

export function GroupStagePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const round = Number(params.get("round") ?? "1");
  const view = params.get("view");
  const predictedMatches = usePredictionStore((state) => state.predictedMatches);
  const groupResults = usePredictionStore((state) => state.groupResults);
  const groupThirdRanking = usePredictionStore((state) => state.groupThirdRanking);
  const startGroupRoundRun = usePredictionStore((state) => state.startGroupRoundRun);
  const cancelCurrentRun = usePredictionStore((state) => state.cancelCurrentRun);
  const status = usePredictionStore((state) => state.status);
  const running = status === "running" || status === "pending";
  const [startedRound, setStartedRound] = useState(round);
  const roundMatches = useMemo(() => getGroupMatchesByRound(predictedMatches, round), [predictedMatches, round]);

  const startRound = async (targetRound: number) => {
    setStartedRound(targetRound);
    setParams({ round: String(targetRound) });
    const alreadyHasRound = getGroupMatchesByRound(predictedMatches, targetRound).length > 0;
    if (!alreadyHasRound) {
      await startGroupRoundRun(targetRound, 1000);
    }
  };

  const stopPrediction = async () => {
    await cancelCurrentRun();
    setStartedRound(1);
    setParams({ round: "1" });
  };

  if (view === "ranking") {
    return (
      <main className="journeyPage">
        <section className="journeyHeader">
          <div>
            <span className="heroKicker">Group Ranking</span>
            <h1>小组赛排名总览</h1>
            <p>左侧为各小组排名，右侧为小组第三排行榜。</p>
          </div>
          <Space wrap>
            {running && <Button danger onClick={stopPrediction}>停止预测</Button>}
            <Button type="primary" size="large" disabled={running} onClick={() => navigate("/knockout")}>
              进入淘汰赛
            </Button>
          </Space>
        </section>
        <div className="rankingSplit">
          <Card title="各小组排名表" className="glassPanel">
            {Object.entries(groupResults).map(([group, rows]) => (
              <Table<GroupRow>
                key={group}
                title={() => `Group ${group}`}
                size="small"
                rowKey="team_id"
                pagination={false}
                dataSource={rows}
                columns={[
                  { title: "排名", dataIndex: "rank", width: 64 },
                  { title: "球队", dataIndex: "team_name", render: (name, row) => (row.qualified ? <Tag color="green">{name}</Tag> : name) },
                  { title: "积分", dataIndex: "points", width: 64 },
                  { title: "净胜球", dataIndex: "goal_difference", width: 84 },
                  { title: "进球", dataIndex: "goals_for", width: 64 },
                ]}
              />
            ))}
          </Card>
          <GroupThirdRanking />
        </div>
      </main>
    );
  }

  return (
    <main className="journeyPage">
      <section className="journeyHeader">
        <div>
          <span className="heroKicker">Group Stage Round {round}</span>
          <h1>{running ? `正在进行小组赛第 ${startedRound} 轮` : `小组赛第 ${round} 轮比赛结果`}</h1>
          <p>每轮比赛会并行预测；点击任意对决结果，可查看双方实力分析和 Agent 比分解释。</p>
        </div>
        <Space wrap>
          {running ? (
            <Button danger size="large" onClick={stopPrediction}>
              停止预测
            </Button>
          ) : (
            <>
              <Button onClick={() => startRound(1)}>第一轮</Button>
              <Button onClick={() => startRound(2)}>第二轮</Button>
              <Button onClick={() => startRound(3)}>第三轮</Button>
            </>
          )}
        </Space>
      </section>
      <AgentPipelineBanner />
      <RoundMatchBoard matches={roundMatches} />
      <div className="journeyFooter">
        {round < 3 ? (
          <Button type="primary" size="large" disabled={running} onClick={() => startRound(round + 1)}>
            进行小组赛第 {round + 1} 轮
          </Button>
        ) : (
          <Button type="primary" size="large" disabled={running || groupThirdRanking.length === 0} onClick={() => navigate("/group?view=ranking")}>
            下一步
          </Button>
        )}
      </div>
    </main>
  );
}
