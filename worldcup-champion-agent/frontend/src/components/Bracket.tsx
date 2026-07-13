import { Card, Empty, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";
import type { MatchPrediction } from "../types/prediction";
import { percent, stageName } from "../utils/format";

const rounds = ["quarter", "semi", "final"];

export function Bracket() {
  const { knockoutResults, selectMatch } = usePredictionStore();
  const hasData = rounds.some((round) => Array.isArray(knockoutResults[round]));
  if (!hasData) return <Empty description="等待淘汰赛对阵生成" />;
  return (
    <div className="panel">
      <h2>淘汰赛对阵树</h2>
      <div className="bracket">
        {rounds.map((round) => (
          <div key={round} className="roundColumn">
            <h3>{stageName(round)}</h3>
            {((knockoutResults[round] as MatchPrediction[]) ?? []).map((match) => (
              <Card key={match.match_id} hoverable size="small" className="matchCard" onClick={() => selectMatch(match)}>
                <div className="matchTeams">
                  <span>{match.home_team_name}</span>
                  <strong>
                    {match.predicted_home_score}-{match.predicted_away_score}
                  </strong>
                  <span>{match.away_team_name}</span>
                </div>
                <div className="matchMeta">
                  <Tag color="gold">{match.winner_name}</Tag>
                  <span>置信度 {percent(match.confidence)}</span>
                </div>
              </Card>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
