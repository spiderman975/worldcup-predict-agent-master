import { Card, Empty, Progress, Table, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";
import { percent, stageName } from "../utils/format";

export function MatchDetail() {
  const match = usePredictionStore((state) => state.selectedMatch);
  if (!match) return <Empty description="点击比赛卡片查看概率矩阵" />;
  const matrixRows = match.score_matrix.map((row, homeScore) => ({
    key: homeScore,
    homeScore,
    ...Object.fromEntries(row.map((value, awayScore) => [`away${awayScore}`, percent(value)])),
  }));
  return (
    <Card title="单场比赛详情" className="panel">
      <h3>{stageName(match.stage)}</h3>
      <div className="scoreLine">
        {match.home_team_name} <strong>{match.predicted_home_score}-{match.predicted_away_score}</strong> {match.away_team_name}
      </div>
      <Tag color="green">胜者：{match.winner_name ?? "平局"}</Tag>
      <div className="probList">
        <span>主胜</span>
        <Progress percent={Number((match.home_win_prob * 100).toFixed(1))} />
        <span>平局</span>
        <Progress percent={Number((match.draw_prob * 100).toFixed(1))} />
        <span>客胜</span>
        <Progress percent={Number((match.away_win_prob * 100).toFixed(1))} />
      </div>
      <h3>Top 比分</h3>
      <div className="tagList">
        {match.top_scores.map((score) => (
          <Tag key={`${score.home_score}-${score.away_score}`}>{`${score.home_score}-${score.away_score} ${percent(score.probability)}`}</Tag>
        ))}
      </div>
      <h3>比分概率矩阵</h3>
      <Table
        size="small"
        pagination={false}
        scroll={{ x: true }}
        dataSource={matrixRows}
        columns={[
          { title: "主\\客", dataIndex: "homeScore", fixed: "left", width: 64 },
          ...[0, 1, 2, 3, 4, 5].map((score) => ({ title: `${score}`, dataIndex: `away${score}`, width: 72 })),
        ]}
      />
      <h3>关键因素</h3>
      <ul>{match.key_factors.map((item) => <li key={item}>{item}</li>)}</ul>
    </Card>
  );
}
