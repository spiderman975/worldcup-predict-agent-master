import { apiFetch, getApiBaseUrl } from "./predictionApi";

export interface ChatMessage {
  role: "user" | "agent" | "system";
  content: string;
  timestamp: string;
  phase?: string;
  data?: Record<string, unknown>;
  _done?: boolean;
}

export async function createChatSession(): Promise<{ session_id: string }> {
  const response = await apiFetch("/api/chat/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) throw new Error("Failed to create chat session");
  return response.json();
}

export async function sendChatMessage(
  sessionId: string,
  message: string,
  options: { forceWebSearch?: boolean } = {},
) {
  const response = await apiFetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, force_web_search: Boolean(options.forceWebSearch) }),
  });
  if (!response.ok) throw new Error("Failed to send chat message");
  return response.json();
}

export async function startChatPrediction(sessionId: string, monteCarloRuns = 1000) {
  const response = await apiFetch(`/api/chat/sessions/${sessionId}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ monte_carlo_runs: monteCarloRuns }),
  });
  if (!response.ok) throw new Error("Failed to start prediction");
  return response.json() as Promise<{ run_id: string; status: string }>;
}

export function connectChatStream(
  sessionId: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  onError: (error: Event) => void,
) {
  const source = new EventSource(`${getApiBaseUrl()}/api/chat/sessions/${sessionId}/stream`);
  const events = [
    "user_message",
    "agent_message",
    "agent_token",
    "agent_done",
    "agent_error",
    "agent_status",
    "agent_progress",
    "system_message",
    "prediction_start",
    "phase",
    "data_loaded",
    "team_rating",
    "team_rating_complete",
    "group_prediction",
    "group_round_start",
    "group_round_complete",
    "group_match_predicted",
    "knockout_round_start",
    "knockout_match_predicted",
    "bracket_update",
    "animation_step",
    "champion_probability",
    "reasoning",
    "verify",
    "prediction_complete",
    "prediction_error",
    "prediction_canceled",
    "heartbeat",
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
