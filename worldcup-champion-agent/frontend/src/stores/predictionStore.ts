import { create } from "zustand";

import { connectRunStream } from "../api/sseClient";
import { cancelRun, createGroupRoundRun, createRun, getRatings, getRun } from "../api/predictionApi";
import type {
  ChampionProbability,
  GroupRow,
  MatchExplanation,
  MatchPrediction,
  PredictionResult,
  SSEPayload,
  Team,
  TeamOdds,
  VerifierResult,
} from "../types/prediction";

interface PredictionStore {
  currentRunId: string | null;
  streamSource: EventSource | null;
  status: string;
  currentPhase: string;
  teams: Team[];
  matches: unknown[];
  teamOdds: TeamOdds[];
  groupResults: Record<string, GroupRow[]>;
  groupThirdRanking: GroupRow[];
  knockoutResults: Record<string, MatchPrediction[] | string | null>;
  predictedMatches: MatchPrediction[];
  championProbabilities: ChampionProbability[];
  selectedMatch: MatchPrediction | null;
  reasoningSteps: SSEPayload[];
  sseMessages: SSEPayload[];
  animationEvents: SSEPayload[];
  matchExplanations: MatchExplanation[];
  finalChampion: string | null;
  finalReasoning: string | null;
  verifierResult: VerifierResult | null;
  error: string | null;
  startRun: (monteCarloRuns: number, enableRealtimeSearch: boolean, mode?: string, knockoutRound?: string) => Promise<void>;
  startModeRun: (mode: string, monteCarloRuns?: number, knockoutRound?: string) => Promise<void>;
  startGroupRoundRun: (roundNumber: number, monteCarloRuns?: number) => Promise<void>;
  cancelCurrentRun: () => Promise<void>;
  connectStream: (runId: string) => void;
  handleSSEEvent: (event: SSEPayload) => void;
  selectMatch: (match: MatchPrediction | null) => void;
  loadRunResult: (runId: string) => Promise<void>;
  loadRatings: () => Promise<void>;
  reset: () => void;
}

function mergeMatch(list: MatchPrediction[], match: MatchPrediction) {
  const rest = list.filter((item) => item.match_id !== match.match_id);
  return [...rest, match];
}

function emptyState() {
  return {
    currentRunId: null,
    streamSource: null,
    status: "idle",
    currentPhase: "IDLE",
    groupResults: {},
    groupThirdRanking: [],
    knockoutResults: {},
    predictedMatches: [],
    championProbabilities: [],
    selectedMatch: null,
    reasoningSteps: [],
    sseMessages: [],
    animationEvents: [],
    matchExplanations: [],
    finalChampion: null,
    finalReasoning: null,
    verifierResult: null,
    error: null,
  };
}

function applyResult(set: (partial: Partial<PredictionStore>) => void, result: PredictionResult) {
  set({
    currentRunId: result.run_id,
    status: result.status,
    currentPhase: result.current_phase,
    teams: result.teams,
    matches: result.matches,
    teamOdds: result.team_odds ?? [],
    groupResults: result.group_results?.group_tables ?? {},
    groupThirdRanking: result.group_third_ranking ?? result.group_results?.third_place_ranking ?? [],
    knockoutResults: result.knockout_results ?? {},
    predictedMatches: result.predicted_matches ?? [],
    championProbabilities: result.champion_probabilities ?? [],
    matchExplanations: result.match_explanations ?? [],
    finalChampion: result.final_champion,
    finalReasoning: result.final_reasoning,
    verifierResult: result.verifier_result,
    reasoningSteps: result.reasoning_steps ?? [],
    selectedMatch: result.predicted_matches?.[0] ?? null,
  });
}

function getMatchGroup(match: MatchPrediction, teams: Team[], schedules: unknown[]) {
  const schedule = schedules.find((item) => typeof item === "object" && item !== null && (item as { match_id?: string }).match_id === match.match_id) as
    | { group?: string }
    | undefined;
  if (schedule?.group) return schedule.group;
  return teams.find((team) => team.team_id === match.home_team_id)?.group ?? "";
}

function buildGroupTables(teams: Team[], schedules: unknown[], predictions: MatchPrediction[]) {
  const tables = teams.reduce<Record<string, Record<string, GroupRow>>>((acc, team) => {
    acc[team.group] = acc[team.group] ?? {};
    acc[team.group][team.team_id] = {
      team_id: team.team_id,
      team_name: team.name,
      group: team.group,
      played: 0,
      points: 0,
      goals_for: 0,
      goals_against: 0,
      goal_difference: 0,
      qualified: false,
      rank: 0,
    };
    return acc;
  }, {});

  predictions.filter((match) => match.stage === "group").forEach((match) => {
    const group = getMatchGroup(match, teams, schedules);
    const home = tables[group]?.[match.home_team_id];
    const away = tables[group]?.[match.away_team_id];
    if (!home || !away) return;
    const hs = match.predicted_home_score;
    const as = match.predicted_away_score;
    home.played += 1;
    away.played += 1;
    home.goals_for += hs;
    home.goals_against += as;
    away.goals_for += as;
    away.goals_against += hs;
    if (hs > as) home.points += 3;
    else if (as > hs) away.points += 3;
    else {
      home.points += 1;
      away.points += 1;
    }
  });

  const groupResults: Record<string, GroupRow[]> = {};
  const thirdRows: GroupRow[] = [];
  Object.entries(tables).forEach(([group, rows]) => {
    const sorted = Object.values(rows)
      .map((row) => ({ ...row, goal_difference: row.goals_for - row.goals_against }))
      .sort((a, b) => b.points - a.points || b.goal_difference - a.goal_difference || b.goals_for - a.goals_for);
    sorted.forEach((row, index) => {
      row.rank = index + 1;
      row.qualified = index < 2;
      if (index === 2) thirdRows.push({ ...row, group });
    });
    groupResults[group] = sorted;
  });
  const groupThirdRanking = thirdRows
    .sort((a, b) => b.points - a.points || b.goal_difference - a.goal_difference || b.goals_for - a.goals_for)
    .map((row, index) => ({ ...row, third_rank: index + 1 }));
  return { groupResults, groupThirdRanking };
}

export const usePredictionStore = create<PredictionStore>((set, get) => ({
  ...emptyState(),
  teams: [],
  matches: [],
  teamOdds: [],

  startRun: async (monteCarloRuns, enableRealtimeSearch, mode = "full", knockoutRound) => {
    get().streamSource?.close();
    set({
      ...emptyState(),
      teams: get().teams,
      matches: get().matches,
      teamOdds: get().teamOdds,
      status: "pending",
      currentPhase: "CREATING",
    });
    const response = await createRun({
      monte_carlo_runs: monteCarloRuns,
      enable_realtime_search: enableRealtimeSearch,
      mode,
      knockout_round: knockoutRound,
    });
    set({ currentRunId: response.run_id, status: response.status });
    get().connectStream(response.run_id);
  },

  startModeRun: async (mode, monteCarloRuns = 1000, knockoutRound) => {
    await get().startRun(monteCarloRuns, false, mode, knockoutRound);
  },

  startGroupRoundRun: async (roundNumber, monteCarloRuns = 1000) => {
    get().streamSource?.close();
    set({
      status: "pending",
      currentPhase: "CREATING",
      error: null,
      sseMessages: [],
      reasoningSteps: [],
      animationEvents: [],
    });
    const response = await createGroupRoundRun(roundNumber, monteCarloRuns);
    set({ currentRunId: response.run_id, status: response.status });
    get().connectStream(response.run_id);
  },

  cancelCurrentRun: async () => {
    const runId = get().currentRunId;
    get().streamSource?.close();
    if (runId) {
      try {
        await cancelRun(runId);
      } catch {
        // 如果任务已自然结束，也按用户意图恢复预测前状态。
      }
    }
    get().reset();
  },

  connectStream: (runId) => {
    get().streamSource?.close();
    const source = connectRunStream(
      runId,
      get().handleSSEEvent,
      () => set({ error: "SSE 连接异常，请确认后端服务仍在运行。" }),
      () => {
        if (get().status !== "idle") get().loadRunResult(runId);
      },
    );
    set({ streamSource: source });
  },

  handleSSEEvent: (event) => {
    set((state) => ({
      sseMessages: [...state.sseMessages, event],
      reasoningSteps: [...state.reasoningSteps, event],
      animationEvents: event.event === "animation_step" ? [...state.animationEvents, event] : state.animationEvents,
      currentPhase: event.phase ?? state.currentPhase,
      status: event.event === "prediction_complete" ? "completed" : state.status === "pending" ? "running" : state.status,
    }));

    if (event.event === "prediction_canceled") {
      get().reset();
      return;
    }
    if (event.event === "data_loaded") {
      set({ teams: (event.data.teams as Team[]) ?? [], matches: (event.data.matches as unknown[]) ?? [] });
    }
    if (event.event === "team_rating_complete") {
      set({ teamOdds: (event.data.team_odds as TeamOdds[]) ?? [] });
    }
    if (event.event === "group_match_predicted" || event.event === "knockout_match_predicted") {
      const match = event.data.match as MatchPrediction | undefined;
      const explanation = event.data.explanation as MatchExplanation | undefined;
      if (match) {
        set((state) => ({
          predictedMatches: mergeMatch(state.predictedMatches, match),
          selectedMatch: state.selectedMatch ?? match,
        }));
        const nextMatches = mergeMatch(get().predictedMatches, match);
        const tables = buildGroupTables(get().teams, get().matches, nextMatches);
        set({
          groupResults: tables.groupResults,
          groupThirdRanking: tables.groupThirdRanking,
        });
      }
      if (explanation) {
        set((state) => ({
          matchExplanations: [...state.matchExplanations.filter((item) => item.match_id !== explanation.match_id), explanation],
        }));
      }
    }
    if (event.event === "group_prediction") {
      const groupResults = event.data.group_results as { group_tables?: Record<string, GroupRow[]>; group_stage_predictions?: MatchPrediction[] };
      set({
        groupResults: groupResults?.group_tables ?? {},
        groupThirdRanking: (event.data.third_place_ranking as GroupRow[]) ?? [],
        predictedMatches: [...get().predictedMatches, ...(groupResults?.group_stage_predictions ?? [])].reduce<MatchPrediction[]>((acc, match) => mergeMatch(acc, match), []),
      });
    }
    if (event.event === "bracket_update") {
      const knockoutResults = (event.data.knockout_results as Record<string, MatchPrediction[] | string | null>) ?? {};
      const knockoutMatches = ["quarter", "semi", "final"].flatMap((round) => (Array.isArray(knockoutResults[round]) ? (knockoutResults[round] as MatchPrediction[]) : []));
      set((state) => ({
        knockoutResults,
        predictedMatches: [...state.predictedMatches, ...knockoutMatches].reduce<MatchPrediction[]>((acc, match) => mergeMatch(acc, match), []),
      }));
    }
    if (event.event === "champion_probability") {
      set({
        championProbabilities: (event.data.champion_probabilities as ChampionProbability[]) ?? [],
        finalChampion: (event.data.final_champion as string) ?? null,
      });
    }
    if (event.event === "reasoning") {
      set({ finalReasoning: event.data.final_reasoning as string });
    }
    if (event.event === "verify") {
      set({ verifierResult: event.data.verifier_result as VerifierResult });
    }
    if (event.event === "prediction_error") {
      set({ status: "failed", error: event.message });
    }
  },

  selectMatch: (match) => set({ selectedMatch: match }),

  loadRunResult: async (runId) => {
    const result = (await getRun(runId)) as PredictionResult;
    if (result.status !== "canceled" && result.group_results?.group_tables) applyResult(set, result);
  },

  loadRatings: async () => {
    const result = await getRatings();
    set({ teamOdds: result.team_odds ?? [] });
  },

  reset: () => {
    get().streamSource?.close();
    set({ ...emptyState(), teams: get().teams, matches: get().matches, teamOdds: get().teamOdds });
  },
}));
