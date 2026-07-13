import { Table, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";
import type { GroupRow } from "../types/prediction";

export function GroupStagePanel() {
  const groupResults = usePredictionStore((state) => state.groupResults);
  return (
    <div className="panel">
      <h2>小组赛积分榜</h2>
      {Object.entries(groupResults).map(([group, rows]) => (
        <div key={group} className="groupBlock">
          <h3>Group {group}</h3>
          <Table<GroupRow>
            size="small"
            rowKey="team_id"
            pagination={false}
            dataSource={rows}
            columns={[
              { title: "排名", dataIndex: "rank", width: 56 },
              { title: "队伍", dataIndex: "team_name", render: (name, row) => (row.qualified ? <Tag color="green">{name}</Tag> : name) },
              { title: "积分", dataIndex: "points", width: 56 },
              { title: "进球", dataIndex: "goals_for", width: 56 },
              { title: "失球", dataIndex: "goals_against", width: 56 },
              { title: "净胜球", dataIndex: "goal_difference", width: 72 },
            ]}
          />
        </div>
      ))}
    </div>
  );
}
