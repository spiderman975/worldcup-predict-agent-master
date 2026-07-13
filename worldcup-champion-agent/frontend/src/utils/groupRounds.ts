import type { MatchPrediction, Team } from "../types/prediction";

export function groupTeamsByGroup(teams: Team[]) {
  return teams.reduce<Record<string, Team[]>>((acc, team) => {
    acc[team.group] = [...(acc[team.group] ?? []), team];
    return acc;
  }, {});
}

export function getGroupRound(match: MatchPrediction) {
  const number = Number(match.match_id.replace(/^[A-Z]+/, ""));
  if ([1, 6].includes(number)) return 1;
  if ([2, 5].includes(number)) return 2;
  return 3;
}

export function getGroupMatchesByRound(matches: MatchPrediction[], round: number) {
  return matches
    .filter((match) => match.stage === "group" && getGroupRound(match) === round)
    .sort((a, b) => a.match_id.localeCompare(b.match_id));
}

export function getMatchExplanation(matchId: string, explanations: { match_id: string; text: string }[]) {
  return explanations.find((item) => item.match_id === matchId)?.text;
}
