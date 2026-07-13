import { Card, Table, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";
import type { GroupRow } from "../types/prediction";

export function GroupThirdRanking() {
  const rows = usePredictionStore((state) => state.groupThirdRanking);
  return (
    <Card title="小组第三排行榜" className="panel">
      <Table<GroupRow>
        size="small"
        rowKey={(row) => `${row.team_id}-${row.rank}`}
        pagination={false}
        dataSource={rows}
        columns={[
          { title: "第三排名", dataIndex: "third_rank", width: 86 },
          { title: "小组", dataIndex: "group", width: 60, render: (group) => <Tag>{group}</Tag> },
          { title: "球队", dataIndex: "team_name" },
          { title: "积分", dataIndex: "points", width: 60 },
          { title: "净胜球", dataIndex: "goal_difference", width: 80 },
          { title: "进球", dataIndex: "goals_for", width: 60 },
        ]}
      />
    </Card>
  );
}
