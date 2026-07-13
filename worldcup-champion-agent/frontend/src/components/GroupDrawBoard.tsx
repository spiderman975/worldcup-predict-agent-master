import { Card, Tag } from "antd";

import type { Team } from "../types/prediction";
import { groupTeamsByGroup } from "../utils/groupRounds";

interface Props {
  teams: Team[];
}

export function GroupDrawBoard({ teams }: Props) {
  const groups = groupTeamsByGroup(teams);
  return (
    <div className="groupDrawGrid">
      {Object.entries(groups).map(([group, rows]) => (
        <Card key={group} className="glassPanel groupCard" title={`Group ${group}`}>
          {rows.map((team) => (
            <div className="teamSeed" key={team.team_id}>
              <Tag color="gold">{team.team_id}</Tag>
              <span>{team.name}</span>
            </div>
          ))}
        </Card>
      ))}
    </div>
  );
}
