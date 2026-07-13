export interface Team {
  team_id: string;
  name: string;
  group: string;
  fifa_rank: number;
  elo_rating: number;
  attack_score: number;
  defense_score: number;
  recent_form: number;
  worldcup_history_score: number;
  squad_availability_score: number;
}

export interface TeamOdds {
  team_id: string;
  team_name: string;
  group: string;
  overall_rating: number;
  attack_strength: number;
  defense_strength: number;
  form_score: number;
  implied_probability: number;
  decimal_odds: number;
  explanation_factors: string[];
}

export interface MatchPrediction {
  match_id: string;
  stage: string;
  home_team_id: string;
  away_team_id: string;
  home_team_name: string;
  away_team_name: string;
  predicted_home_score: number;
  predicted_away_score: number;
  home_win_prob: number;
  draw_prob: number;
  away_win_prob: number;
  score_matrix: number[][];
  top_scores: { home_score: number; away_score: number; probability: number }[];
  winner: string | null;
  winner_name: string | null;
  confidence: number;
  key_factors: string[];
  explanation?: string;
}

export interface GroupRow {
  team_id: string;
  team_name: string;
  group?: string;
  played: number;
  points: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  qualified: boolean;
  rank: number;
  third_rank?: number;
}

export interface ChampionProbability {
  team_id: string;
  team_name: string;
  probability: number;
}

export interface VerifierResult {
  passed: boolean;
  warnings: string[];
  errors: string[];
}

export interface SSEPayload {
  event: string;
  run_id: string;
  phase?: string;
  message: string;
  data: Record<string, unknown>;
}

export interface MatchExplanation {
  match_id: string;
  stage: string;
  text: string;
  metadata: Record<string, unknown>;
}

export interface PredictionResult {
  run_id: string;
  status: string;
  current_phase: string;
  teams: Team[];
  matches: unknown[];
  team_odds?: TeamOdds[];
  group_results: {
    group_tables?: Record<string, GroupRow[]>;
    group_stage_predictions?: MatchPrediction[];
    third_place_ranking?: GroupRow[];
  };
  group_third_ranking?: GroupRow[];
  knockout_results: Record<string, MatchPrediction[] | string>;
  predicted_matches: MatchPrediction[];
  match_explanations?: MatchExplanation[];
  champion_probabilities: ChampionProbability[];
  reasoning_steps: SSEPayload[];
  final_champion: string | null;
  final_reasoning: string | null;
  verifier_result: VerifierResult | null;
  errors: string[];
}
