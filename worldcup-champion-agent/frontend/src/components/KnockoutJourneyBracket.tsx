import { Card, Empty, Tag } from "antd";
import { useState } from "react";

import type { MatchPrediction } from "../types/prediction";
import { MatchInsightModal } from "./MatchInsightModal";

interface Props {
  knockoutResults: Record<string, MatchPrediction[] | string | null>;
  visibleRounds: string[];
}

const rounds = [
  { key: "quarter", label: "1/4 决赛" },
  { key: "semi", label: "1/2 决赛" },
  { key: "final", label: "决赛" },
];

function tieBreakNote(match: MatchPrediction) {
  if (match.predicted_home_score !== match.predicted_away_score || !match.winner) return null;
  const homeWins = match.winner === match.home_team_id;
  const penaltyHome = homeWins ? 5 : 4;
  const penaltyAway = homeWins ? 4 : 5;
  return `90分钟平局，点球 ${penaltyHome}-${penaltyAway}`;
}

function MatchNode({ match, onClick }: { match: MatchPrediction; onClick: () => void }) {
  const note = tieBreakNote(match);
  const homeWinner = match.winner === match.home_team_id;
  const awayWinner = match.winner === match.away_team_id;
  return (
    <button className="bracketNode" onClick={onClick}>
      <div className={homeWinner ? "winnerLine" : ""}>
        <span>{match.home_team_id}</span>
        <strong>{match.predicted_home_score}</strong>
      </div>
      <div className={awayWinner ? "winnerLine" : ""}>
        <span>{match.away_team_id}</span>
        <strong>{match.predicted_away_score}</strong>
      </div>
      <Tag color="green">晋级 {match.winner}</Tag>
      {note ? <small>{note}</small> : null}
    </button>
  );
}

export function KnockoutJourneyBracket({ knockoutResults, visibleRounds }: Props) {
  const [active, setActive] = useState<MatchPrediction | null>(null);
  const hasMatches = rounds.some((round) => Array.isArray(knockoutResults[round.key]));
  if (!hasMatches) return <Empty description="淘汰赛还未进行" />;
  const quarterMatches = visibleRounds.includes("quarter") && Array.isArray(knockoutResults.quarter) ? knockoutResults.quarter : [];
  const semiMatches = visibleRounds.includes("semi") && Array.isArray(knockoutResults.semi) ? knockoutResults.semi : [];
  const finalMatches = visibleRounds.includes("final") && Array.isArray(knockoutResults.final) ? knockoutResults.final : [];
  const leftQuarters = quarterMatches.slice(0, 2);
  const rightQuarters = quarterMatches.slice(2, 4);
  const leftSemi = semiMatches.slice(0, 1);
  const rightSemi = semiMatches.slice(1, 2);
  return (
    <>
      <div className="journeyBracket">
        <div className="bracketWing leftWing">
          <div className="bracketRound">
            <h3>{rounds[0].label}</h3>
            {leftQuarters.length ? leftQuarters.map((match) => <MatchNode key={match.match_id} match={match} onClick={() => setActive(match)} />) : <div className="bracketPlaceholder">等待 1/4 决赛</div>}
          </div>
          <div className="bracketRound semiRound">
            <h3>{rounds[1].label}</h3>
            {leftSemi.length ? leftSemi.map((match) => <MatchNode key={match.match_id} match={match} onClick={() => setActive(match)} />) : <div className="bracketPlaceholder">等待左侧胜者</div>}
          </div>
        </div>
        <div className="finalColumn">
          <h3>{rounds[2].label}</h3>
          {finalMatches.length ? finalMatches.map((match) => <MatchNode key={match.match_id} match={match} onClick={() => setActive(match)} />) : <div className="bracketPlaceholder">等待决赛</div>}
        </div>
        <div className="bracketWing rightWing">
          <div className="bracketRound semiRound">
            <h3>{rounds[1].label}</h3>
            {rightSemi.length ? rightSemi.map((match) => <MatchNode key={match.match_id} match={match} onClick={() => setActive(match)} />) : <div className="bracketPlaceholder">等待右侧胜者</div>}
          </div>
          <div className="bracketRound">
            <h3>{rounds[0].label}</h3>
            {rightQuarters.length ? rightQuarters.map((match) => <MatchNode key={match.match_id} match={match} onClick={() => setActive(match)} />) : <div className="bracketPlaceholder">等待 1/4 决赛</div>}
          </div>
        </div>
      </div>
      <MatchInsightModal match={active} open={Boolean(active)} onClose={() => setActive(null)} />
    </>
  );
}
