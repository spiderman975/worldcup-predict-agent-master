import { getApiBaseUrl } from "./predictionApi";
import type { SSEPayload } from "../types/prediction";

export function connectRunStream(
  runId: string,
  onEvent: (payload: SSEPayload) => void,
  onError: (error: Event) => void,
  onComplete: () => void,
) {
  // EventSource 会自动重连；任务完成后我们主动关闭，避免浏览器一直保持连接。
  const source = new EventSource(`${getApiBaseUrl()}/api/runs/${runId}/stream`);
  const events = [
    "prediction_start",
    "phase",
    "data_loaded",
    "team_rating",
    "team_rating_complete",
    "agent_thought",
    "agent_node",
    "data_scout_update",
    "match_pipeline_start",
    "group_prediction",
    "group_round_start",
    "group_round_complete",
    "group_match_predicted",
    "match_predicted",
    "knockout_round_start",
    "knockout_match_predicted",
    "bracket_update",
    "animation_step",
    "simulation_progress",
    "champion_probability",
    "reasoning",
    "verify",
    "prediction_complete",
    "prediction_error",
    "prediction_canceled",
  ];
  events.forEach((eventName) => {
    source.addEventListener(eventName, (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as SSEPayload;
      onEvent(payload);
      if (eventName === "prediction_complete" || eventName === "prediction_error" || eventName === "prediction_canceled") {
        source.close();
        onComplete();
      }
    });
  });
  source.onerror = onError;
  return source;
}
