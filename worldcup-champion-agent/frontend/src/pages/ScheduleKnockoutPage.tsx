import { Alert, Button, Empty, Modal, Progress, Spin, Tag, message } from "antd";
import { useEffect, useMemo, useState } from "react";

import { getMatches, predictMatch, type Match } from "../api/predictionApi";
import { stageName, stageOrder, type MatchStage } from "../utils/format";

type KnockoutStage = Exclude<MatchStage, "group" | "third_place">;

const KNOCKOUT_ROUNDS: { key: KnockoutStage; size: number }[] = [
  { key: "round_of_32", size: 16 },
  { key: "round_of_16", size: 8 },
  { key: "quarter", size: 4 },
  { key: "semi", size: 2 },
  { key: "final", size: 1 },
];

const statusLabels: Record<string, string> = {
  scheduled: "未开赛",
  live: "进行中",
  finished: "已完赛",
  result_pending: "赛果待同步",
  postponed: "延期",
  cancelled: "取消",
};

const statusColors: Record<string, string> = {
  scheduled: "blue",
  live: "red",
  finished: "green",
  result_pending: "orange",
  postponed: "default",
  cancelled: "red",
};

function sortMatches(a: Match, b: Match) {
  const timeDiff = new Date(a.match_time).getTime() - new Date(b.match_time).getTime();
  if (Number.isFinite(timeDiff) && timeDiff !== 0) return timeDiff;
  return a.match_id.localeCompare(b.match_id);
}

function formatMatchTime(value?: string) {
  if (!value) return "时间待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function scoreText(match?: Match | null) {
  if (!match || match.actual_home_score == null || match.actual_away_score == null || match.status !== "finished") return "vs";
  return `${match.actual_home_score}-${match.actual_away_score}`;
}

function winnerSide(match?: Match | null) {
  if (!match || match.status !== "finished") return null;
  if (match.actual_home_score == null || match.actual_away_score == null) return null;
  if (match.actual_home_score === match.actual_away_score) return null;
  return match.actual_home_score > match.actual_away_score ? "home" : "away";
}

function useRealtimeMode(match: Match) {
  const diff = new Date(match.match_time).getTime() - Date.now();
  return diff >= 0 && diff <= 30 * 60 * 1000;
}

function PredictionSummary({ record }: { record: any }) {
  const prediction = record?.prediction ?? record;
  const explanation = record?.explanation ?? prediction?.explanation;
  return (
    <div className="predictionSummary">
      <h3>{record?.match?.home_team_name} vs {record?.match?.away_team_name}</h3>
      <div className="scoreLine">{prediction?.predicted_home_score} - {prediction?.predicted_away_score}</div>
      <div className="probGrid">
        <Progress percent={Math.round((prediction?.home_win_prob ?? 0) * 100)} size="small" format={(v) => `主胜 ${v}%`} />
        <Progress percent={Math.round((prediction?.draw_prob ?? 0) * 100)} size="small" format={(v) => `平局 ${v}%`} />
        <Progress percent={Math.round((prediction?.away_win_prob ?? 0) * 100)} size="small" format={(v) => `客胜 ${v}%`} />
      </div>
      <p>{explanation || "暂无分析说明。"}</p>
      <Tag color={record?.mode === "realtime" ? "red" : "blue"}>{record?.mode === "realtime" ? "实时增强" : "历史实力"}</Tag>
      {record?.created_at && <span className="predictionTime">{new Date(record.created_at).toLocaleString("zh-CN")}</span>}
    </div>
  );
}

function MatchNode({
  match,
  stage,
  predicting,
  onPredict,
  onOpenAnalysis,
}: {
  match: Match | null;
  stage: MatchStage;
  predicting: boolean;
  onPredict: (match: Match, realtime: boolean) => void;
  onOpenAnalysis: (record: any, match: Match) => void;
}) {
  const winner = winnerSide(match);
  const realtime = match ? useRealtimeMode(match) : false;
  const canPredict = Boolean(match && (match.status === "scheduled" || match.status === "live") && match.home_team_name && match.away_team_name);
  const saved = match?.saved_prediction;
  return (
    <div className={`knockoutNode ${match ? "" : "knockoutNode--placeholder"}`}>
      <div className="knockoutNodeMeta">
        <Tag color={match ? "blue" : "default"}>{stageName(match?.stage ?? stage, match?.stage_number)}</Tag>
        <span>{formatMatchTime(match?.match_time)}</span>
        <Tag color={statusColors[match?.status ?? ""] ?? "default"}>{match ? statusLabels[match.status ?? ""] ?? "状态未知" : "待定"}</Tag>
      </div>
      {match ? (
        <>
          <div className="knockoutVersus">
            <div className={`knockoutTeam ${winner === "home" ? "knockoutTeam--winner" : ""} ${winner === "away" ? "knockoutTeam--loser" : ""}`}>
              <span>{match.home_team_name}</span>
            </div>
            <strong>{scoreText(match)}</strong>
            <div className={`knockoutTeam ${winner === "away" ? "knockoutTeam--winner" : ""} ${winner === "home" ? "knockoutTeam--loser" : ""}`}>
              <span>{match.away_team_name}</span>
            </div>
          </div>
          <div className="knockoutActions">
            <Button
              size="small"
              type="primary"
              disabled={!canPredict}
              loading={predicting}
              onClick={() => onPredict(match, realtime)}
            >
              {canPredict ? (realtime ? "实时增强预测" : "预测比分") : match.status === "result_pending" ? "赛果待同步" : "不可预测"}
            </Button>
          </div>
          {saved && (
            <div className="knockoutPrediction">
              <strong>预测 {saved.predicted_home_score}-{saved.predicted_away_score}</strong>
              <span>主胜 {Math.round(saved.home_win_prob * 100)}% / 平 {Math.round(saved.draw_prob * 100)}% / 客胜 {Math.round(saved.away_win_prob * 100)}%</span>
              <span>{saved.mode === "realtime" ? "实时增强" : "历史实力"} · {saved.created_at ? new Date(saved.created_at).toLocaleString("zh-CN") : "已保存"}</span>
              <Button size="small" onClick={() => onOpenAnalysis({ prediction: saved, mode: saved.mode, created_at: saved.created_at, explanation: saved.explanation, match }, match)}>
                查看分析
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="knockoutPending">对阵待定</div>
          <Button size="small" disabled>待对阵确定</Button>
        </>
      )}
    </div>
  );
}

export function ScheduleKnockoutPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [predicting, setPredicting] = useState<Record<string, boolean>>({});
  const [analysis, setAnalysis] = useState<any | null>(null);

  const loadMatches = (forceRefresh = false) =>
    getMatches({ forceRefresh })
      .then((items) => setMatches(items))
      .catch((err) => setError(err instanceof Error ? err.message : "淘汰赛赛程加载失败"))
      .finally(() => setLoading(false));

  useEffect(() => {
    loadMatches();
  }, []);

  const grouped = useMemo(() => {
    const byStage = new Map<string, Match[]>();
    for (const match of [...matches].sort((a, b) => stageOrder(a.stage) - stageOrder(b.stage) || sortMatches(a, b))) {
      byStage.set(match.stage, [...(byStage.get(match.stage) ?? []), match]);
    }
    return byStage;
  }, [matches]);

  const handlePredict = async (match: Match, realtime: boolean) => {
    setPredicting((current) => ({ ...current, [match.match_id]: true }));
    try {
      const record = await predictMatch(match.match_id, { realtime });
      setAnalysis(record);
      message.success("预测比分已生成。");
      await loadMatches(true);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "预测失败");
    } finally {
      setPredicting((current) => ({ ...current, [match.match_id]: false }));
    }
  };

  const thirdPlaceMatches = grouped.get("third_place") ?? [];

  if (loading) {
    return (
      <div className="loadingState">
        <Spin />
        <span>正在加载淘汰赛对阵...</span>
      </div>
    );
  }

  if (error) return <Alert type="error" showIcon message="淘汰赛赛程加载失败" description={error} />;

  return (
    <div className="pageStack knockoutPage">
      <div className="pageTitle">
        <h1>淘汰赛对阵</h1>
        <p>真实树只使用官方赛程和真实赛果；预测比分仅显示在当前节点，不推进后续轮次。</p>
      </div>
      <div className="knockoutScroller">
        <div className="knockoutTree">
          {KNOCKOUT_ROUNDS.map((round) => {
            const roundMatches = (grouped.get(round.key) ?? []).slice(0, round.size);
            const nodes = Array.from({ length: round.size }, (_, index) => roundMatches[index] ?? null);
            return (
              <section className={`knockoutRound knockoutRound--${round.key}`} key={round.key}>
                <h2>{stageName(round.key)}</h2>
                <div className="knockoutRoundNodes">
                  {nodes.map((match, index) => (
                    <MatchNode
                      key={match?.match_id ?? `${round.key}-${index}`}
                      match={match}
                      stage={round.key}
                      predicting={Boolean(match && predicting[match.match_id])}
                      onPredict={handlePredict}
                      onOpenAnalysis={(record) => setAnalysis(record)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>
      <section className="thirdPlacePanel">
        <h2>季军赛</h2>
        {thirdPlaceMatches.length ? (
          thirdPlaceMatches.sort(sortMatches).map((match) => (
            <MatchNode
              key={match.match_id}
              match={match}
              stage="third_place"
              predicting={Boolean(predicting[match.match_id])}
              onPredict={handlePredict}
              onOpenAnalysis={(record) => setAnalysis(record)}
            />
          ))
        ) : (
          <Empty description="季军赛对阵待定" />
        )}
      </section>
      <Modal open={Boolean(analysis)} title="预测分析" footer={null} onCancel={() => setAnalysis(null)} width={760}>
        {analysis && <PredictionSummary record={analysis} />}
      </Modal>
    </div>
  );
}
