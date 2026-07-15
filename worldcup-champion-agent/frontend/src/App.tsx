import {
  CalendarOutlined,
  HomeOutlined,
  MessageOutlined,
  ReadOutlined,
  TeamOutlined,
  TrophyOutlined,
} from "@ant-design/icons";
import { Button, ConfigProvider, Empty, Layout, Menu, Modal, Progress, Space, Spin, Tag, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";

import {
  getCachedMatches,
  getCachedRatings,
  getCachedSchedule,
  getCachedTeams,
  getMatches,
  getRatings,
  getSchedule,
  getTeamDetail,
  getTeams,
  connectMatchPredictionStream,
  startMatchPrediction,
} from "./api/predictionApi";
import { ChatPanel } from "./components/ChatPanel";

type Team = {
  team_id: string;
  name: string;
  group: string;
  fifa_rank: number;
  attack_score: number;
  defense_score: number;
  recent_form: number;
  elo_rating: number;
  squad_availability_score?: number;
};

type TeamPlayer = {
  name: string;
  attack: number;
  defense: number;
  overall: number;
  injured: boolean;
  injury_description?: string;
  is_starter?: boolean;
};

type TeamDetail = Team & {
  rating?: Rating;
  starting_lineup?: string[];
  injured_players?: TeamPlayer[];
  players?: TeamPlayer[];
  database?: {
    members_count?: number;
    computed_attack?: number;
    computed_defensive?: number;
    streak?: number;
  };
};

type Match = {
  match_id: string;
  group?: string | null;
  stage: string;
  stage_number?: number;
  home_team_id: string;
  away_team_id: string;
  home_team_name: string;
  away_team_name: string;
  match_time: string;
  match_date: string;
  venue?: string;
  status?: string;
  actual_home_score?: number | null;
  actual_away_score?: number | null;
};

type Rating = {
  team_id: string;
  name: string;
  overall_rating: number;
  attack_strength: number;
  defense_strength: number;
  explanation_factors?: string[];
};

const QUIET_REFRESH_MS = 3 * 60 * 1000;

type ProgressItem = {
  event: string;
  message: string;
  phase?: string;
  status?: string;
};

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function stageLabel(stage: string, stageNumber?: number) {
  const labels: Record<string, string> = {
    group: "小组赛",
    round_of_32: "1/16决赛（32强）",
    round_of_16: "1/8决赛（16强）",
    quarter: "1/4决赛",
    semi: "半决赛",
    final: "决赛",
    third_place: "三四名决赛",
  };
  return labels[stage] ?? (stageNumber ? `第 ${stageNumber} 阶段` : stage);
}

function Shell() {
  const location = useLocation();
  const [chatVisible, setChatVisible] = useState(false);
  const selectedKey = location.pathname === "/" ? "/home" : location.pathname.split("/").slice(0, 2).join("/");

  return (
    <Layout className="appShell">
      <div className="globalWorldcupBg" />
      <Layout.Sider width={238} className="sideNav">
        <div className="brandBlock">
          <strong>WorldCup Agent</strong>
          <span>赛程驱动的单场预测系统</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={[
            { key: "/home", icon: <HomeOutlined />, label: <Link to="/home">主页</Link> },
            { key: "/schedule", icon: <CalendarOutlined />, label: <Link to="/schedule">世界杯赛程表</Link> },
            { key: "/teams", icon: <TeamOutlined />, label: <Link to="/teams">球队信息</Link> },
            { key: "/results", icon: <TrophyOutlined />, label: <Link to="/results">比赛结果概览</Link> },
          ]}
        />
      </Layout.Sider>
      <Layout.Content className="contentShell">
        <Routes>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/schedule/:date" element={<MatchDayPage />} />
          <Route path="/teams" element={<TeamsPage />} />
          <Route path="/teams/:teamId" element={<TeamDetailPage />} />
          <Route path="/results" element={<ResultsPage />} />
        </Routes>
      </Layout.Content>
      {!chatVisible && (
        <Button
          className="chatFloatBtn"
          type="primary"
          shape="circle"
          size="large"
          icon={<MessageOutlined />}
          aria-label="打开 Agent 对话"
          title="Agent 对话"
          onClick={() => setChatVisible(true)}
        />
      )}
      <ChatPanel visible={chatVisible} onClose={() => setChatVisible(false)} />
    </Layout>
  );
}

function PageTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="pageTitle">
      <h1>{title}</h1>
      {sub && <p>{sub}</p>}
    </div>
  );
}

function LoadingState({ text = "正在加载中..." }: { text?: string }) {
  return (
    <div className="loadingState">
      <Spin />
      <span>{text}</span>
    </div>
  );
}

function HomePage() {
  return (
    <div className="pageStack">
      <section className="homeHero">
        <div>
          <Tag color="blue">2026 database schedule</Tag>
          <h1>世界杯比赛预测主系统</h1>
          <p>
            以数据库赛程为轴组织赛程、球队与单场预测。Chat Agent 负责理解你的问题，并在需要时启动单场多 Agent 工作流。
          </p>
        </div>
        <div className="newsRail">
          <div className="newsCard"><ReadOutlined /> 赛前 30 分钟：实时信息增强预测入口</div>
          <div className="newsCard"><CalendarOutlined /> 手动按钮：基于历史实力执行单场预测</div>
          <div className="newsCard"><TrophyOutlined /> 赛后视图：展示真实比分与已保存理由</div>
        </div>
      </section>
      <section className="videoBand">
        <div className="videoMock">
          <div className="videoPulse" />
          <span>World Cup live board</span>
        </div>
      </section>
    </div>
  );
}

function SchedulePage() {
  const cachedSchedule = getCachedSchedule();
  const [dates, setDates] = useState<{ date: string; matches: Match[] }[]>(cachedSchedule?.dates ?? []);
  const [loading, setLoading] = useState(!cachedSchedule);
  const navigate = useNavigate();

  useEffect(() => {
    getSchedule().then((res) => setDates(res.dates)).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      getSchedule({ forceRefresh: true }).then((res) => setDates(res.dates)).catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  if (loading) return <LoadingState text="正在加载赛程..." />;
  return (
    <div className="pageStack">
      <PageTitle title="世界杯赛程表" sub="点击比赛日查看当日对阵。已完赛日期会以绿色标注，赛程数据优先来自 SQLite 数据库。" />
      <div className="calendarGrid">
        {dates.map((day) => {
          const finished = day.matches.length > 0 && day.matches.every((match) => match.status === "finished");
          const finishedCount = day.matches.filter((match) => match.status === "finished").length;
          return (
            <button key={day.date} className={`dateTile ${finished ? "dateTile--finished" : ""}`} onClick={() => navigate(`/schedule/${day.date}`)}>
              <span>{formatDate(day.date)}</span>
              <strong>{day.matches.length} 场</strong>
              <small>{finished ? "已完赛" : `${finishedCount} 场已完赛`}</small>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function MatchDayPage() {
  const { date } = useParams();
  const cachedMatches = getCachedMatches();
  const [matches, setMatches] = useState<Match[]>(() => (cachedMatches ?? []).filter((match) => match.match_date === date));
  const [loading, setLoading] = useState(!cachedMatches);
  const [predicting, setPredicting] = useState<string | null>(null);
  const [prediction, setPrediction] = useState<any | null>(null);
  const [progressItems, setProgressItems] = useState<Record<string, ProgressItem[]>>({});

  useEffect(() => {
    const cached = getCachedMatches();
    if (cached) {
      setMatches(cached.filter((match) => match.match_date === date));
      setLoading(false);
    }
    getMatches().then((items) => setMatches(items.filter((match) => match.match_date === date))).finally(() => setLoading(false));
  }, [date]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      getMatches({ forceRefresh: true }).then((items) => setMatches(items.filter((match) => match.match_date === date))).catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [date]);

  const handlePredict = async (matchId: string) => {
    setPredicting(matchId);
    setProgressItems((prev) => ({
      ...prev,
      [matchId]: [{ event: "prediction_start", message: "正在启动单场预测工作流...", status: "running" }],
    }));
    try {
      const { run_id } = await startMatchPrediction(matchId);
      const source = connectMatchPredictionStream(
        run_id,
        (event, payload) => {
          const message = String(payload.message ?? payload.data?.message ?? event);
          if (event === "agent_progress" || event === "agent_node" || event === "data_scout_update" || event === "prediction_start") {
            setProgressItems((prev) => ({
              ...prev,
              [matchId]: [
                ...(prev[matchId] ?? []),
                {
                  event,
                  message,
                  phase: String(payload.phase ?? payload.data?.phase ?? ""),
                  status: String(payload.data?.status ?? (event === "prediction_start" ? "running" : "completed")),
                },
              ],
            }));
          }
          if (event === "prediction_complete") {
            setPrediction(payload.data?.record ?? null);
            setProgressItems((prev) => ({
              ...prev,
              [matchId]: [...(prev[matchId] ?? []), { event, message: "预测完成", status: "completed" }],
            }));
            setPredicting(null);
            source.close();
          }
          if (event === "prediction_error") {
            setProgressItems((prev) => ({
              ...prev,
              [matchId]: [...(prev[matchId] ?? []), { event, message, status: "failed" }],
            }));
            setPredicting(null);
            source.close();
          }
        },
        () => {
          setProgressItems((prev) => ({
            ...prev,
            [matchId]: [...(prev[matchId] ?? []), { event: "prediction_error", message: "预测事件流连接异常", status: "failed" }],
          }));
          setPredicting(null);
          source.close();
        },
      );
    } finally {
      // The SSE terminal event will clear predicting.
    }
  };

  if (loading) return <LoadingState text="正在加载当天比赛..." />;
  return (
    <div className="pageStack">
      <PageTitle title={`${date} 对阵安排`} sub="已完赛场次展示数据库比分；未赛场次可手动生成模型预测。" />
      <div className="matchList">
        {matches.length === 0 && <Empty description="当天没有赛程" />}
        {matches.map((match) => (
          <div className="matchRow" key={match.match_id}>
            <div className="matchMeta">
              <Tag>{match.match_id}</Tag>
              <Tag color="blue">{stageLabel(match.stage, match.stage_number)}</Tag>
              <span>{formatTime(match.match_time)}</span>
              {match.venue && <span>{match.venue}</span>}
            </div>
            <div className="teamsLine">
              <strong>{match.home_team_name}</strong>
              <span>{match.status === "finished" ? `${match.actual_home_score}-${match.actual_away_score}` : "vs"}</span>
              <strong>{match.away_team_name}</strong>
            </div>
            {match.status === "finished" ? (
              <Tag color="green">已完赛 {match.actual_home_score}-{match.actual_away_score}</Tag>
            ) : (
              <Button type="primary" loading={predicting === match.match_id} onClick={() => handlePredict(match.match_id)}>
                预测比赛结果
              </Button>
            )}
            {progressItems[match.match_id]?.length > 0 && (
              <div className="inlineProgress">
                <strong>推理流程</strong>
                {progressItems[match.match_id].slice(-8).map((item, index) => (
                  <div className={`progressStep progressStep--${item.status ?? "running"}`} key={`${item.event}-${index}`}>
                    <span />
                    <p>{item.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <Modal open={Boolean(prediction)} title="单场预测结果" onCancel={() => setPrediction(null)} footer={null} width={760}>
        {prediction && <PredictionSummary record={prediction} />}
      </Modal>
    </div>
  );
}

function PredictionSummary({ record }: { record: any }) {
  const pred = record.prediction;
  const analysis = String(record.analysis ?? pred.explanation ?? record.explanation?.text ?? "暂无原因分析。");
  return (
    <div className="predictionSummary">
      <h3>{record.match.home_team_name} vs {record.match.away_team_name}</h3>
      <div className="scoreLine">{pred.predicted_home_score} - {pred.predicted_away_score}</div>
      <div className="predictionAnalysis">
        {analysis.split(/\n{2,}/).map((block, index) => {
          const lines = block.split("\n").filter(Boolean);
          const [title, ...body] = lines;
          return (
            <section key={`${title}-${index}`}>
              {body.length > 0 ? <h4>{title}</h4> : null}
              {(body.length > 0 ? body : [title]).map((line) => <p key={line}>{line}</p>)}
            </section>
          );
        })}
      </div>
      <div className="probGrid">
        <Progress percent={Math.round(pred.home_win_prob * 100)} size="small" format={(v) => `主胜 ${v}%`} />
        <Progress percent={Math.round(pred.draw_prob * 100)} size="small" format={(v) => `平局 ${v}%`} />
        <Progress percent={Math.round(pred.away_win_prob * 100)} size="small" format={(v) => `客胜 ${v}%`} />
      </div>
    </div>
  );
}

function TeamsPage() {
  const cachedTeams = getCachedTeams();
  const cachedRatings = getCachedRatings();
  const [teams, setTeams] = useState<Team[]>(cachedTeams ?? []);
  const [ratings, setRatings] = useState<Record<string, Rating>>(cachedRatings?.team_ratings ?? {});
  const [loading, setLoading] = useState(!cachedTeams || !cachedRatings);
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([getTeams(), getRatings()]).then(([teamItems, ratingRes]) => {
      setTeams(teamItems);
      setRatings(ratingRes.team_ratings ?? {});
    }).finally(() => setLoading(false));
  }, []);

  if (loading && teams.length === 0) return <LoadingState text="球队信息正在加载中..." />;

  return (
    <div className="pageStack">
      <PageTitle title="球队信息" sub="展示本地基础数据中的球队、分组和攻防实力。点击球队查看详情。" />
      <div className="teamGrid">
        {teams.map((team) => {
          const rating = ratings[team.team_id];
          return (
            <button className="teamCard" key={team.team_id} onClick={() => navigate(`/teams/${team.team_id}`)}>
              <span>{team.group} 组</span>
              <strong>{team.name}</strong>
              <small>FIFA #{team.fifa_rank}</small>
              <Progress percent={Math.round((rating?.overall_rating ?? 0) * 100)} size="small" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TeamDetailPage() {
  const { teamId } = useParams();
  const cachedTeams = getCachedTeams();
  const [teams, setTeams] = useState<Team[]>(cachedTeams ?? []);
  const [detail, setDetail] = useState<TeamDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const team = useMemo(() => teams.find((item) => item.team_id === teamId), [teams, teamId]);

  useEffect(() => {
    getTeams().then(setTeams);
  }, []);

  useEffect(() => {
    if (!teamId) return;
    setLoadingDetail(true);
    getTeamDetail(teamId)
      .then(setDetail)
      .finally(() => setLoadingDetail(false));
  }, [teamId]);

  const currentTeam = detail ?? team;
  if (!currentTeam) return <LoadingState text="正在加载球队信息..." />;
  const rating = detail?.rating;
  const players = detail?.players ?? [];
  const starters = players.filter((player) => player.is_starter);
  const substitutes = players.filter((player) => !player.is_starter);

  return (
    <div className="pageStack">
      <PageTitle title={currentTeam.name} sub={`${currentTeam.group} 组，FIFA 排名 ${currentTeam.fifa_rank}`} />
      <div className="detailPanel">
        <div className="teamDetailStats">
          <div>
            <strong>{rating ? Math.round(rating.overall_rating * 100) : Math.round(((currentTeam.attack_score + currentTeam.defense_score) / 2) * 100)}</strong>
            <span>综合评分</span>
          </div>
          <div>
            <strong>{currentTeam.elo_rating}</strong>
            <span>Elo 估计</span>
          </div>
          <div>
            <strong>{detail?.database?.members_count ?? (players.length || "-")}</strong>
            <span>球员数量</span>
          </div>
          <div>
            <strong>{players.filter((player) => player.injured).length}</strong>
            <span>伤病人数</span>
          </div>
        </div>
        <Progress percent={Math.round(currentTeam.attack_score * 100)} format={(v) => `进攻 ${v}%`} />
        <Progress percent={Math.round(currentTeam.defense_score * 100)} format={(v) => `防守 ${v}%`} />
        <Progress percent={Math.round(currentTeam.recent_form * 100)} format={(v) => `状态 ${v}%`} />
        <Progress percent={Math.round((currentTeam.squad_availability_score ?? 1) * 100)} format={(v) => `阵容可用性 ${v}%`} />
        {rating?.explanation_factors?.length ? (
          <div className="factorList">
            {rating.explanation_factors.map((factor: string) => <Tag key={factor}>{factor}</Tag>)}
          </div>
        ) : null}
      </div>

      {loadingDetail && <LoadingState text="正在加载球员阵容..." />}
      {!loadingDetail && players.length === 0 && <Empty description="暂无球员阵容数据" />}
      {players.length > 0 && (
        <div className="rosterLayout">
          <section className="rosterSection">
            <h3>预计首发阵容</h3>
            <div className="playerGrid playerGrid--compact">
              {(starters.length ? starters : players.slice(0, 11)).map((player) => (
                <PlayerCard key={player.name} player={player} />
              ))}
            </div>
          </section>
          <section className="rosterSection">
            <h3>全队球员评分</h3>
            <div className="playerGrid">
              {[...starters, ...substitutes].map((player) => (
                <PlayerCard key={player.name} player={player} showStarter />
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function PlayerCard({ player, showStarter = false }: { player: TeamPlayer; showStarter?: boolean }) {
  return (
    <div className={`playerCard ${player.injured ? "playerCard--injured" : ""}`}>
      <div className="playerCardHeader">
        <strong>{player.name}</strong>
        <Space size={4}>
          {showStarter && player.is_starter && <Tag color="blue">首发</Tag>}
          {player.injured && <Tag color="red">伤病</Tag>}
        </Space>
      </div>
      <div className="playerScores">
        <span>综合 {Math.round(player.overall)}</span>
        <span>进攻 {player.attack}</span>
        <span>防守 {player.defense}</span>
      </div>
      {player.injured && player.injury_description && <small>{player.injury_description}</small>}
    </div>
  );
}

function ResultsPage() {
  const cachedMatches = getCachedMatches();
  const [matches, setMatches] = useState<Match[]>(cachedMatches ?? []);

  useEffect(() => {
    getMatches().then(setMatches);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      getMatches({ forceRefresh: true }).then(setMatches).catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="pageStack">
      <PageTitle title="比赛结果概览" sub="已完赛显示数据库真实比分；未赛比赛可通过赛程页或 Chat Agent 生成并保存预测。" />
      <div className="matchList">
        {matches.map((match) => (
          <div className="matchRow" key={match.match_id}>
            <div className="matchMeta">
              <Tag>{match.match_id}</Tag>
              <span>{match.match_date}</span>
            </div>
            <div className="teamsLine">
              <strong>{match.home_team_name}</strong>
              <span>{match.status === "finished" ? `${match.actual_home_score}-${match.actual_away_score}` : "未赛"}</span>
              <strong>{match.away_team_name}</strong>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          borderRadius: 8,
          colorPrimary: "#2563eb",
          fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        },
      }}
    >
      <Shell />
    </ConfigProvider>
  );
}
