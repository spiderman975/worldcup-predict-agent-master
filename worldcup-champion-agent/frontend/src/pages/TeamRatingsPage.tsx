import { Button, Card, Table, Tag } from "antd";
import { useEffect } from "react";

import { usePredictionStore } from "../stores/predictionStore";
import type { TeamOdds } from "../types/prediction";
import { percent } from "../utils/format";

export function TeamRatingsPage() {
  const { teamOdds, loadRatings, startModeRun } = usePredictionStore();
  useEffect(() => {
    if (teamOdds.length === 0) loadRatings();
  }, [loadRatings, teamOdds.length]);

  return (
    <Card
      title="球队评分、综合实力与展示赔率"
      className="panel"
      extra={<Button onClick={() => startModeRun("ratings", 1000)}>实时触发评分流程</Button>}
    >
      <Table<TeamOdds>
        rowKey="team_id"
        dataSource={teamOdds}
        columns={[
          { title: "球队", dataIndex: "team_name", render: (name, row) => <span>{name} <Tag>{row.group}</Tag></span> },
          { title: "综合评分", dataIndex: "overall_rating", sorter: (a, b) => a.overall_rating - b.overall_rating },
          { title: "攻击", dataIndex: "attack_strength" },
          { title: "防守", dataIndex: "defense_strength" },
          { title: "状态", dataIndex: "form_score" },
          { title: "隐含概率", dataIndex: "implied_probability", render: percent },
          { title: "展示赔率", dataIndex: "decimal_odds" },
        ]}
        expandable={{
          expandedRowRender: (row) => <span>{row.explanation_factors.join("；")}</span>,
        }}
      />
    </Card>
  );
}
