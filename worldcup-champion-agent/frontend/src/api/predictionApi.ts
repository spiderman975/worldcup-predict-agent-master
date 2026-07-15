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

type CacheEntry<T> = {
  value?: T;
  promise?: Promise<T>;
  expiresAt: number;
};

const FRONTEND_CACHE_TTL = {
  teams: 30 * 60 * 1000,
  ratings: 30 * 60 * 1000,
  matches: 15 * 60 * 1000,
  schedule: 15 * 60 * 1000,
};

const frontendCache = new Map<string, CacheEntry<unknown>>();

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

function getCachedValue<T>(key: string): T | undefined {
  const entry = frontendCache.get(key) as CacheEntry<T> | undefined;
  if (!entry || entry.expiresAt <= Date.now()) return undefined;
  return entry.value;
}

function rememberFrontend<T>(key: string, ttlMs: number, loader: () => Promise<T>, forceRefresh = false): Promise<T> {
  const now = Date.now();
  const current = frontendCache.get(key) as CacheEntry<T> | undefined;
  if (!forceRefresh && current && current.expiresAt > now) {
    if (current.value !== undefined) return Promise.resolve(current.value);
    if (current.promise) return current.promise;
  }
  const promise = loader()
    .then((value) => {
      frontendCache.set(key, { value, expiresAt: Date.now() + ttlMs });
      return value;
    })
    .catch((error) => {
      frontendCache.delete(key);
      throw error;
    });
  frontendCache.set(key, { promise, expiresAt: now + ttlMs });
  return promise;
}

export function getCachedTeams() {
  return getCachedValue<any[]>("teams");
}

export function getCachedMatches() {
  return getCachedValue<any[]>("matches");
}

export function getCachedSchedule() {
  return getCachedValue<{ dates: { date: string; matches: any[] }[] }>("schedule");
}

export function getCachedRatings() {
  return getCachedValue<any>("ratings");
}

export function clearFrontendDataCache() {
  frontendCache.delete("matches");
  frontendCache.delete("schedule");
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
  return rememberFrontend("teams", FRONTEND_CACHE_TTL.teams, async () =>
    readJson<any[]>(await apiFetch("/api/teams"), "Failed to load teams"),
  );
}

export async function getTeamDetail(teamId: string) {
  return readJson<any>(await apiFetch(`/api/teams/${encodeURIComponent(teamId)}`), "Failed to load team detail");
}

export async function getMatches(options: { forceRefresh?: boolean } = {}) {
  return rememberFrontend(
    "matches",
    FRONTEND_CACHE_TTL.matches,
    async () => readJson<any[]>(await apiFetch("/api/matches"), "Failed to load matches"),
    options.forceRefresh,
  );
}

export async function getSchedule(options: { forceRefresh?: boolean } = {}) {
  return rememberFrontend(
    "schedule",
    FRONTEND_CACHE_TTL.schedule,
    async () => readJson<{ dates: { date: string; matches: any[] }[] }>(await apiFetch("/api/matches/schedule"), "Failed to load schedule"),
    options.forceRefresh,
  );
}

export async function predictMatch(matchId: string) {
  const result = await readJson<any>(await apiFetch(`/api/matches/${encodeURIComponent(matchId)}/predict`, { method: "POST" }), "Failed to predict match");
  clearFrontendDataCache();
  return result;
}

export async function startMatchPrediction(matchId: string) {
  return readJson<{ run_id: string; match_id: string; status: string }>(
    await apiFetch(`/api/matches/${encodeURIComponent(matchId)}/predict/start`, { method: "POST" }),
    "Failed to start match prediction",
  );
}

export function connectMatchPredictionStream(
  runId: string,
  onEvent: (event: string, data: Record<string, any>) => void,
  onError: (error: Event) => void,
) {
  const source = new EventSource(`${getApiBaseUrl()}/api/matches/predict-runs/${runId}/stream`);
  const events = [
    "prediction_start",
    "agent_node",
    "agent_progress",
    "data_scout_update",
    "prediction_complete",
    "prediction_error",
  ];
  events.forEach((eventName) => {
    source.addEventListener(eventName, (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      onEvent(eventName, data);
    });
  });
  source.onerror = onError;
  return source;
}

export async function getMatchPrediction(matchId: string) {
  return readJson<any>(await apiFetch(`/api/matches/${encodeURIComponent(matchId)}/prediction`), "Failed to load match prediction");
}

export async function getRatings() {
  return rememberFrontend("ratings", FRONTEND_CACHE_TTL.ratings, async () =>
    readJson<any>(await apiFetch("/api/ratings"), "Failed to load ratings"),
  );
}

export async function searchTeams(query: string) {
  return readJson<any>(await apiFetch(`/api/search/teams?q=${encodeURIComponent(query)}`), "检索球队失败");
}

export async function searchMatchExplanations(query: string) {
  return readJson<any>(await apiFetch(`/api/search/match-explanations?q=${encodeURIComponent(query)}`), "检索比赛解释失败");
}

export const API_BASE_URL = CONFIGURED_API_BASE_URL;
