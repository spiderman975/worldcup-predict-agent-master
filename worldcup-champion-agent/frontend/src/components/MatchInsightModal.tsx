import { Descriptions, Modal, Progress, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";
import type { MatchPrediction } from "../types/prediction";
import { percent, stageName } from "../utils/format";
import { getMatchExplanation } from "../utils/groupRounds";

interface Props {
  match: MatchPrediction | null;
  open: boolean;
  onClose: () => void;
}

export function MatchInsightModal({ match, open, onClose }: Props) {
  const teamOdds = usePredictionStore((state) => state.teamOdds);
  const explanations = usePredictionStore((state) => state.matchExplanations);
  if (!match) return null;
  const home = teamOdds.find((item) => item.team_id === match.home_team_id);
  const away = teamOdds.find((item) => item.team_id === match.away_team_id);
  const explanation = match.explanation ?? getMatchExplanation(match.match_id, explanations) ?? "Agent 正在生成这场比赛的解释。";
  return (
    <Modal open={open} onCancel={onClose} footer={null} width={780} title={`${stageName(match.stage)}：${match.home_team_name} vs ${match.away_team_name}`}>
      <div className="modalScoreLine">
        <span>{match.home_team_name}</span>
        <strong>{match.predicted_home_score}-{match.predicted_away_score}</strong>
        <span>{match.away_team_name}</span>
        <Tag color="gold">胜者：{match.winner_name ?? "平局"}</Tag>
      </div>
      <div className="modalColumns">
        <Descriptions size="small" bordered column={1} title={match.home_team_name}>
          <Descriptions.Item label="综合评分">{home?.overall_rating ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="攻击强度">{home?.attack_strength ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="防守强度">{home?.defense_strength ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="展示赔率">{home?.decimal_odds ?? "-"}</Descriptions.Item>
        </Descriptions>
        <Descriptions size="small" bordered column={1} title={match.away_team_name}>
          <Descriptions.Item label="综合评分">{away?.overall_rating ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="攻击强度">{away?.attack_strength ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="防守强度">{away?.defense_strength ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="展示赔率">{away?.decimal_odds ?? "-"}</Descriptions.Item>
        </Descriptions>
      </div>
      <div className="probList">
        <span>主胜 {percent(match.home_win_prob)}</span>
        <Progress percent={Number((match.home_win_prob * 100).toFixed(1))} />
        <span>平局 {percent(match.draw_prob)}</span>
        <Progress percent={Number((match.draw_prob * 100).toFixed(1))} />
        <span>客胜 {percent(match.away_win_prob)}</span>
        <Progress percent={Number((match.away_win_prob * 100).toFixed(1))} />
      </div>
      <div className="agentExplainBox">
        <strong>Agent 解释</strong>
        <p>{explanation}</p>
      </div>
    </Modal>
  );
}
