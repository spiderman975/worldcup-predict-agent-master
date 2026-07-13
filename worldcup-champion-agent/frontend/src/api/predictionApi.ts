const CONFIGURED_API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const API_BASE_URL_CANDIDATES = Array.from(
  new Set([
    CONFIGURED_API_BASE_URL,
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
  ]),
);

let activeApiBaseUrl = CONFIGURED_API_BASE_URL;

type RunCreateResponse = {
  run_id: string;
  status: string;
};

function withBaseUrl(baseUrl: string, path: string) {
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export function getApiBaseUrl() {
  return activeApiBaseUrl;
}

export async function apiFetch(path: string, init?: RequestInit) {
  let lastError: unknown;
  for (const baseUrl of API_BASE_URL_CANDIDATES) {
    try {
      const response = await fetch(withBaseUrl(baseUrl, path), init);
      activeApiBaseUrl = baseUrl;
      return response;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Backend API is unavailable");
}

async function readJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || message);
  }
  return response.json();
}

export async function createRun(config: { monte_carlo_runs: number; enable_realtime_search: boolean; mode?: string; knockout_round?: string }): Promise<RunCreateResponse> {
  return readJson<RunCreateResponse>(await apiFetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  }), "创建预测任务失败");
}

export async function createModeRun(mode: string, monteCarloRuns: number, knockoutRound?: string): Promise<RunCreateResponse> {
  const endpoint = mode === "full" ? "/api/runs" : mode === "knockout" ? `/api/runs/knockout/${knockoutRound ?? "final"}` : `/api/runs/${mode}`;
  return readJson<RunCreateResponse>(await apiFetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ monte_carlo_runs: monteCarloRuns, enable_realtime_search: false, mode, knockout_round: knockoutRound }),
  }), "创建预测任务失败");
}

export async function createGroupRoundRun(roundNumber: number, monteCarloRuns: number): Promise<RunCreateResponse> {
  return readJson<RunCreateResponse>(await apiFetch(`/api/runs/group-round/${roundNumber}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ monte_carlo_runs: monteCarloRuns, enable_realtime_search: false, mode: "group_round", group_round: roundNumber }),
  }), "创建小组赛预测任务失败");
}

export async function getRun(runId: string) {
  return readJson(await apiFetch(`/api/runs/${runId}`), "获取预测结果失败");
}

export async function cancelRun(runId: string) {
  return readJson(await apiFetch(`/api/runs/${runId}/cancel`, { method: "POST" }), "停止预测任务失败");
}

export async function getTeams() {
  return readJson<any[]>(await apiFetch("/api/teams"), "获取球队失败");
}

export async function getMatches() {
  return readJson<any[]>(await apiFetch("/api/matches"), "获取赛程失败");
}

export async function getSchedule() {
  return readJson<{ dates: { date: string; matches: any[] }[] }>(await apiFetch("/api/matches/schedule"), "获取赛程日历失败");
}

export async function predictMatch(matchId: string) {
  return readJson<any>(await apiFetch(`/api/matches/${encodeURIComponent(matchId)}/predict`, { method: "POST" }), "单场预测失败");
}

export async function getMatchPrediction(matchId: string) {
  return readJson<any>(await apiFetch(`/api/matches/${encodeURIComponent(matchId)}/prediction`), "获取单场预测失败");
}

export async function getRatings() {
  return readJson<any>(await apiFetch("/api/ratings"), "获取球队评分失败");
}

export async function searchTeams(query: string) {
  return readJson<any>(await apiFetch(`/api/search/teams?q=${encodeURIComponent(query)}`), "检索球队失败");
}

export async function searchMatchExplanations(query: string) {
  return readJson<any>(await apiFetch(`/api/search/match-explanations?q=${encodeURIComponent(query)}`), "检索比赛解释失败");
}

export const API_BASE_URL = CONFIGURED_API_BASE_URL;
