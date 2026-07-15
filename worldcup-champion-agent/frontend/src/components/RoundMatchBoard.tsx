import { Card, Empty, Tag } from "antd";
import { useState } from "react";

import { usePredictionStore } from "../stores/predictionStore";
import type { MatchPrediction } from "../types/prediction";
import { MatchInsightModal } from "./MatchInsightModal";

interface Props {
  matches: MatchPrediction[];
}

export function RoundMatchBoard({ matches }: Props) {
  const selectMatch = usePredictionStore((state) => state.selectMatch);
  const [active, setActive] = useState<MatchPrediction | null>(null);
  if (matches.length === 0) return <Empty description="等待本轮比赛结果生成" />;
  const grouped = matches.reduce<Record<string, MatchPrediction[]>>((acc, match, index) => {
    const group = String(Math.floor(index / 4) + 1);
    acc[group] = [...(acc[group] ?? []), match];
    return acc;
  }, {});
  return (
    <>
      <div className="roundGroupGrid">
        {Object.entries(grouped).map(([group, groupMatches]) => (
          <Card key={group} title={`第 ${group} 组`} className="glassPanel">
            <div className="roundMatchList">
              {groupMatches.map((match) => (
                <button
                  className="matchResultButton"
                  key={match.match_id}
                  onClick={() => {
                    selectMatch(match);
                    setActive(match);
                  }}
                >
                  <div className="matchTeamRow">
                    <span title={match.home_team_name}>{match.home_team_name}</span>
                    <span title={match.away_team_name}>{match.away_team_name}</span>
                  </div>
                  <strong className="matchScoreText">{match.predicted_home_score}-{match.predicted_away_score}</strong>
                  <Tag className="matchWinnerTag" color={match.winner ? "blue" : "default"}>
                    {match.winner_name ?? "平局"}
                  </Tag>
                </button>
              ))}
            </div>
          </Card>
        ))}
      </div>
      <MatchInsightModal match={active} open={Boolean(active)} onClose={() => setActive(null)} />
    </>
  );
}
