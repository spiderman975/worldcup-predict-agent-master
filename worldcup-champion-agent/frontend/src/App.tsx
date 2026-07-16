import {
  ApartmentOutlined,
  CalendarOutlined,
  HomeOutlined,
  MessageOutlined,
  OrderedListOutlined,
  TeamOutlined,
  TrophyOutlined,
} from "@ant-design/icons";
import { Button, ConfigProvider, Empty, Layout, Menu, Modal, Progress, Space, Spin, Tag, message, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

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
  getLiveSyncStatus,
  connectMatchPredictionStream,
  predictMatch,
  prefetchCoreData,
  startMatchPrediction,
  triggerLiveSync,
  type LiveSyncStatus,
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
  saved_prediction?: {
    predicted_home_score: number;
    predicted_away_score: number;
    home_win_prob: number;
    draw_prob: number;
    away_win_prob: number;
    mode?: string;
    created_at?: string;
    explanation?: string;
  } | null;
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

function compactStageLabel(stage: string, stageNumber?: number) {
  const labels: Record<string, string> = {
    group: "小组赛",
    round_of_32: "1/16决赛",
    round_of_16: "1/8决赛",
    quarter: "1/4决赛",
    semi: "半决赛",
    third_place: "三四名决赛",
    final: "决赛",
  };
  return labels[stage] ?? (stageNumber ? `第 ${stageNumber} 阶段` : stage);
}

function dateStageLabels(matches: Match[]) {
  const seen = new Set<string>();
  const labels: string[] = [];
  matches.forEach((match) => {
    const label = compactStageLabel(match.stage, match.stage_number);
    if (!seen.has(label)) {
      seen.add(label);
      labels.push(label);
    }
  });
  return labels;
}

function isUnknownTeam(value?: string) {
  const normalized = String(value ?? "").trim().toLowerCase();
  return !normalized || ["tbd", "unknown", "待定"].includes(normalized);
}

function displayTeamName(value?: string) {
  return isUnknownTeam(value) ? "待定" : value;
}

function beijingDateString(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function beijingNowText() {
  return new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}

function matchStatusText(status?: string) {
  const labels: Record<string, string> = {
    scheduled: "未开赛",
    live: "进行中",
    finished: "已完赛",
    result_pending: "赛果待同步",
    postponed: "延期",
    cancelled: "取消",
  };
  return labels[status ?? ""] ?? "状态未知";
}

function matchStatusColor(status?: string) {
  const colors: Record<string, string> = {
    scheduled: "blue",
    live: "red",
    finished: "green",
    result_pending: "orange",
    postponed: "default",
    cancelled: "red",
  };
  return colors[status ?? ""] ?? "default";
}

function displayScore(match: Match) {
  if (match.status === "finished" && match.actual_home_score != null && match.actual_away_score != null) {
    return `${match.actual_home_score}-${match.actual_away_score}`;
  }
  if (match.status === "result_pending") return "赛果待同步";
  return "vs";
}

function isPredictable(match: Match) {
  const teamsReady = !isUnknownTeam(match.home_team_name) && !isUnknownTeam(match.away_team_name);
  return teamsReady && (match.status === "scheduled" || match.status === "live" || !match.status);
}

function isWithinPrematchWindow(match: Match, now = new Date()) {
  const time = new Date(match.match_time).getTime();
  if (!Number.isFinite(time)) return false;
  const diff = time - now.getTime();
  return diff >= 0 && diff <= 30 * 60 * 1000;
}

type GroupStandingRow = {
  team: Team;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goalsFor: number;
  goalsAgainst: number;
  goalDiff: number;
  points: number;
};

const KNOCKOUT_STAGES = ["round_of_32", "round_of_16", "quarter", "semi", "final", "third_place"];
const KNOCKOUT_EXPECTED_COUNTS: Record<string, number> = {
  round_of_32: 16,
  round_of_16: 8,
  quarter: 4,
  semi: 2,
  final: 1,
  third_place: 1,
};

function compareStandings(a: GroupStandingRow, b: GroupStandingRow) {
  return (
    b.points - a.points ||
    b.goalDiff - a.goalDiff ||
    b.goalsFor - a.goalsFor ||
    a.goalsAgainst - b.goalsAgainst ||
    a.team.name.localeCompare(b.team.name)
  );
}

function isFinishedWithScore(match: Match) {
  return match.status === "finished" && match.actual_home_score != null && match.actual_away_score != null;
}

function buildGroupStandings(teams: Team[], matches: Match[]) {
  const rows = new Map<string, GroupStandingRow>();
  teams.forEach((team) => {
    rows.set(team.team_id, {
      team,
      played: 0,
      wins: 0,
      draws: 0,
      losses: 0,
      goalsFor: 0,
      goalsAgainst: 0,
      goalDiff: 0,
      points: 0,
    });
  });

  matches
    .filter((match) => match.stage === "group" && isFinishedWithScore(match))
    .forEach((match) => {
      const home = rows.get(match.home_team_id);
      const away = rows.get(match.away_team_id);
      if (!home || !away) return;
      const homeScore = match.actual_home_score ?? 0;
      const awayScore = match.actual_away_score ?? 0;

      home.played += 1;
      away.played += 1;
      home.goalsFor += homeScore;
      home.goalsAgainst += awayScore;
      away.goalsFor += awayScore;
      away.goalsAgainst += homeScore;

      if (homeScore > awayScore) {
        home.wins += 1;
        home.points += 3;
        away.losses += 1;
      } else if (homeScore < awayScore) {
        away.wins += 1;
        away.points += 3;
        home.losses += 1;
      } else {
        home.draws += 1;
        away.draws += 1;
        home.points += 1;
        away.points += 1;
      }

      home.goalDiff = home.goalsFor - home.goalsAgainst;
      away.goalDiff = away.goalsFor - away.goalsAgainst;
    });

  const groups = Array.from(rows.values()).reduce<Record<string, GroupStandingRow[]>>((acc, row) => {
    const group = row.team.group || "未分组";
    acc[group] = acc[group] ?? [];
    acc[group].push(row);
    return acc;
  }, {});

  Object.keys(groups).forEach((group) => groups[group].sort(compareStandings));
  const thirdPlaces = Object.values(groups)
    .map((groupRows) => groupRows[2])
    .filter(Boolean)
    .sort(compareStandings);

  return { groups, thirdPlaces };
}

function sortMatchesByTime(matches: Match[]) {
  return [...matches].sort((a, b) => new Date(a.match_time).getTime() - new Date(b.match_time).getTime());
}

function knockoutMatchesByStage(matches: Match[]) {
  return KNOCKOUT_STAGES.reduce<Record<string, Match[]>>((acc, stage) => {
    acc[stage] = sortMatchesByTime(matches.filter((match) => match.stage === stage));
    return acc;
  }, {});
}

function Shell() {
  const location = useLocation();
  const [chatVisible, setChatVisible] = useState(false);
  const selectedKey = location.pathname === "/" ? "/home" : location.pathname.split("/").slice(0, 2).join("/");

  useEffect(() => {
    prefetchCoreData();
  }, []);

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
            { key: "/groups", icon: <OrderedListOutlined />, label: <Link to="/groups">小组赛分组及排名</Link> },
            { key: "/knockout", icon: <ApartmentOutlined />, label: <Link to="/knockout">淘汰赛晋级树</Link> },
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
          <Route path="/groups" element={<GroupStandingsPage />} />
          <Route path="/knockout" element={<KnockoutBracketPage />} />
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

function liveSyncText(status?: LiveSyncStatus | null) {
  if (!status) return "使用本地数据库数据";
  if (status.running) return "正在同步";
  if (status.status === "missing_api_key") return "未配置实时比分 API";
  if (status.status === "failed") return "最近同步失败";
  if (status.status === "success") return "实时数据已更新";
  return "使用本地数据库数据";
}

function LiveSyncBar({ onRefresh }: { onRefresh: () => Promise<void> }) {
  const [status, setStatus] = useState<LiveSyncStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadStatus = (forceRefresh = false) => {
    getLiveSyncStatus({ forceRefresh }).then(setStatus).catch(() => setStatus(null));
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const result = await triggerLiveSync();
      setStatus(result);
      if (result.status === "missing_api_key") {
        message.warning(result.message || "未配置实时比分 API，当前使用本地数据库数据。");
      } else if (result.status === "failed") {
        message.error("实时同步失败，已保留本地数据库数据。");
      } else {
        message.success("实时数据刷新完成。");
      }
      await onRefresh();
      loadStatus(true);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "实时同步失败");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="liveSyncBar">
      <span>北京时间：{beijingNowText()}</span>
      <Tag color={status?.status === "success" ? "green" : status?.status === "missing_api_key" ? "orange" : "blue"}>
        {liveSyncText(status)}
      </Tag>
      <span>最近成功：{status?.last_success_at ? new Date(status.last_success_at).toLocaleString("zh-CN") : "暂无"}</span>
      <Button size="small" loading={refreshing} onClick={handleRefresh}>
        立即刷新
      </Button>
    </div>
  );
}

function HomePage() {
  return (
    <div className="pageStack">
      <section className="homeHero">
        <div className="homeHeroContent">
          <span className="homeEyebrow">WorldCup Agent</span>
          <h1>世界杯赛程驱动的单场预测系统</h1>
          <p>
            一个陪你实时追随世界杯的系统。聚合赛程、球队阵容、实时新闻与数据库比分，围绕每一场比赛完成预测、赛果同步、积分排名和淘汰赛路径更新。
          </p>
          <div className="homeStats">
            <span>赛前预测</span>
            <span>赛后同步</span>
            <span>实时搜索</span>
            <span>Harness 协作</span>
          </div>
        </div>
        <div className="homeHeroPanel">
          <strong>World Cup</strong>
          <span>从赛程到预测，从比分到晋级。</span>
        </div>
      </section>
      <section className="videoBand">
        <video className="homeVideo" src="/assets/home-worldcup.mp4" controls muted loop playsInline preload="metadata" />
      </section>
    </div>
  );
}

function SchedulePage() {
  const cachedSchedule = getCachedSchedule();
  const [dates, setDates] = useState<{ date: string; matches: Match[] }[]>(cachedSchedule?.dates ?? []);
  const [loading, setLoading] = useState(!cachedSchedule);
  const [predicting, setPredicting] = useState<string | null>(null);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view");

  const refreshSchedule = async () => {
    const res = await getSchedule({ forceRefresh: true });
    setDates(res.dates);
  };

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
  const today = beijingDateString();
  const allMatches = dates.flatMap((day) => day.matches);
  const futurePredictable = allMatches
    .filter((match) => isPredictable(match) && new Date(match.match_time).getTime() >= Date.now() - 3 * 60 * 60 * 1000)
    .sort((a, b) => new Date(a.match_time).getTime() - new Date(b.match_time).getTime());
  const prematchMatches = futurePredictable.filter((match) => isWithinPrematchWindow(match));
  const nextFutureMatch = futurePredictable[0];
  const todayMatches = dates.find((day) => day.date === today)?.matches ?? [];
  const nextDay = dates.find((day) => day.date > today);

  const handlePredict = async (match: Match, realtime: boolean) => {
    setPredicting(match.match_id);
    try {
      await predictMatch(match.match_id, { realtime });
      message.success("预测已生成并保存。");
      await refreshSchedule();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "预测失败");
    } finally {
      setPredicting(null);
    }
  };

  return (
    <div className="pageStack">
      <LiveSyncBar onRefresh={refreshSchedule} />
      <PageTitle title="世界杯赛程表" sub="点击比赛日查看当日对阵。已完赛日期会以绿色标注，赛程数据优先来自 SQLite 数据库。" />
      {view === "prematch" && (
        <section className="focusPanel">
          <h2>赛前 30 分钟实时增强</h2>
          {prematchMatches.length > 0 ? (
            prematchMatches.map((match) => (
              <div className="matchRow matchRow--highlight" key={match.match_id}>
                <div className="matchMeta">
                  <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
                  <span>{formatDate(match.match_date)} {formatTime(match.match_time)}</span>
                </div>
                <div className="teamsLine">
                  <strong>{displayTeamName(match.home_team_name)}</strong>
                  <span>{displayScore(match)}</span>
                  <strong>{displayTeamName(match.away_team_name)}</strong>
                </div>
                <Button type="primary" loading={predicting === match.match_id} onClick={() => handlePredict(match, true)}>
                  实时增强预测
                </Button>
              </div>
            ))
          ) : (
            <Empty
              description={
                nextFutureMatch
                  ? `当前 30 分钟内没有即将开始的比赛。下一场：${displayTeamName(nextFutureMatch.home_team_name)} vs ${displayTeamName(nextFutureMatch.away_team_name)}`
                  : "当前没有未来可预测比赛。"
              }
            />
          )}
        </section>
      )}
      {view === "manual" && (
        <section className="focusPanel">
          <h2>手动单场预测</h2>
          {futurePredictable.length > 0 ? futurePredictable.slice(0, 8).map((match) => (
            <div className="matchRow" key={match.match_id}>
              <div className="matchMeta">
                <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
                <span>{formatDate(match.match_date)} {formatTime(match.match_time)}</span>
              </div>
              <div className="teamsLine">
                <strong>{displayTeamName(match.home_team_name)}</strong>
                <span>{displayScore(match)}</span>
                <strong>{displayTeamName(match.away_team_name)}</strong>
              </div>
              <Button loading={predicting === match.match_id} onClick={() => handlePredict(match, false)}>
                预测比分
              </Button>
            </div>
          )) : <Empty description="当前没有可手动预测的未来比赛。" />}
        </section>
      )}
      {todayMatches.length === 0 && nextDay && (
        <div className="focusPanel">
          <span>今天没有世界杯比赛。下一比赛日是 {formatDate(nextDay.date)}，共有 {nextDay.matches.length} 场。</span>
          <Button size="small" onClick={() => navigate(`/schedule/${nextDay.date}`)}>查看下一比赛日</Button>
        </div>
      )}
      <div className="calendarGrid">
        {dates.map((day) => {
          const finished = day.matches.length > 0 && day.matches.every((match) => match.status === "finished");
          const finishedCount = day.matches.filter((match) => match.status === "finished").length;
          const pending = day.matches.some((match) => match.status === "result_pending");
          const isToday = day.date === today && !finished && !pending;
          const stageLabels = dateStageLabels(day.matches);
          return (
            <button
              key={day.date}
              className={`dateTile ${finished ? "dateTile--finished" : ""} ${pending ? "dateTile--pending" : ""} ${isToday ? "dateTile--today" : ""}`}
              onClick={() => navigate(`/schedule/${day.date}`)}
            >
              <span>{formatDate(day.date)}</span>
              <div className="dateTileStages">
                {stageLabels.map((label) => (
                  <span key={label}>{label}</span>
                ))}
              </div>
              <strong>{day.matches.length} 场</strong>
              <small>{pending ? "赛果待同步" : finished ? "已完赛" : `${finishedCount} 场已完赛`}</small>
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
              <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
              <Tag color="blue">{stageLabel(match.stage, match.stage_number)}</Tag>
              <span>{formatTime(match.match_time)}</span>
              {match.venue && <span>{match.venue}</span>}
            </div>
            <div className="teamsLine">
              <strong>{displayTeamName(match.home_team_name)}</strong>
              <span>{displayScore(match)}</span>
              <strong>{displayTeamName(match.away_team_name)}</strong>
            </div>
            {match.status === "finished" ? (
              <Tag color="green">已完赛 {match.actual_home_score}-{match.actual_away_score}</Tag>
            ) : match.status === "result_pending" ? (
              <Tag color="orange">赛果待同步</Tag>
            ) : !isPredictable(match) ? (
              <Tag color="default">对阵待定</Tag>
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
      <h3>{displayTeamName(record.match.home_team_name)} vs {displayTeamName(record.match.away_team_name)}</h3>
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

function GroupStandingsPage() {
  const cachedTeams = getCachedTeams();
  const cachedMatches = getCachedMatches();
  const [teams, setTeams] = useState<Team[]>(cachedTeams ?? []);
  const [matches, setMatches] = useState<Match[]>(cachedMatches ?? []);
  const [loading, setLoading] = useState(!cachedTeams || !cachedMatches);

  const refreshData = async (forceRefresh = false) => {
    const [teamItems, matchItems] = await Promise.all([getTeams(), getMatches({ forceRefresh })]);
    setTeams(teamItems);
    setMatches(matchItems);
  };

  useEffect(() => {
    refreshData().finally(() => setLoading(false));
    const timer = window.setInterval(() => {
      refreshData(true).catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const standings = useMemo(() => buildGroupStandings(teams, matches), [teams, matches]);
  const groupNames = Object.keys(standings.groups).sort((a, b) => a.localeCompare(b));

  if (loading && teams.length === 0) return <LoadingState text="正在加载小组排名..." />;

  return (
    <div className="pageStack">
      <LiveSyncBar onRefresh={() => refreshData(true)} />
      <PageTitle
        title="小组赛分组及排名"
        sub="根据数据库中的小组赛真实比分自动计算积分、净胜球和小组第三排名；赛果同步后会随静默刷新更新。"
      />
      <div className="standingsLayout">
        {groupNames.map((group) => (
          <section className="standingPanel" key={group}>
            <div className="standingPanelHeader">
              <h2>{group} 组</h2>
              <Tag color="blue">{standings.groups[group].filter((row) => row.played > 0).length} 队已有赛果</Tag>
            </div>
            <StandingsTable rows={standings.groups[group]} />
          </section>
        ))}
      </div>
      <section className="standingPanel">
        <div className="standingPanelHeader">
          <h2>小组第三排名</h2>
          <Tag color="purple">晋级参考</Tag>
        </div>
        <StandingsTable rows={standings.thirdPlaces} showGroup thirdPlaceRanking />
      </section>
    </div>
  );
}

function StandingsTable({
  rows,
  showGroup = false,
  thirdPlaceRanking = false,
}: {
  rows: GroupStandingRow[];
  showGroup?: boolean;
  thirdPlaceRanking?: boolean;
}) {
  return (
    <div className="standingsTableWrap">
      <table className={`standingsTable ${thirdPlaceRanking ? "standingsTable--thirdPlace" : ""}`}>
        <thead>
          <tr>
            <th>排名</th>
            {showGroup && <th>小组</th>}
            <th>球队</th>
            <th>赛</th>
            <th>胜</th>
            <th>平</th>
            <th>负</th>
            <th>进/失</th>
            <th>净胜</th>
            <th>积分</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.team.team_id}>
              <td>{index + 1}</td>
              {showGroup && <td>{row.team.group || "-"}</td>}
              <td className="standingTeam">{row.team.name}</td>
              <td>{row.played}</td>
              <td>{row.wins}</td>
              <td>{row.draws}</td>
              <td>{row.losses}</td>
              <td>{row.goalsFor}/{row.goalsAgainst}</td>
              <td>{row.goalDiff > 0 ? `+${row.goalDiff}` : row.goalDiff}</td>
              <td className="standingPoints">{row.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KnockoutBracketPage() {
  const cachedMatches = getCachedMatches();
  const [matches, setMatches] = useState<Match[]>(cachedMatches ?? []);
  const [loading, setLoading] = useState(!cachedMatches);
  const [activeStage, setActiveStage] = useState("round_of_32");

  const refreshMatches = async (forceRefresh = false) => {
    setMatches(await getMatches({ forceRefresh }));
  };

  useEffect(() => {
    refreshMatches().finally(() => setLoading(false));
    const timer = window.setInterval(() => {
      refreshMatches(true).catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const byStage = useMemo(() => knockoutMatchesByStage(matches), [matches]);
  const stageTabs = ["round_of_32", "round_of_16", "quarter", "semi", "third_place", "final"];

  if (loading && matches.length === 0) return <LoadingState text="正在加载淘汰赛晋级树..." />;

  return (
    <div className="pageStack pageStack--wide">
      <LiveSyncBar onRefresh={() => refreshMatches(true)} />
      <PageTitle
        title="淘汰赛晋级树状图"
        sub="按阶段切换查看独立对阵图，已完赛节点显示真实比分；未确定对阵保留待定节点，并随赛果同步更新。"
      />
      <div className="knockoutStageTabs">
        {stageTabs.map((stage) => (
          <Button key={stage} type={activeStage === stage ? "primary" : "default"} onClick={() => setActiveStage(stage)}>
            {stageLabel(stage)}
          </Button>
        ))}
      </div>
      <StageBracket stage={activeStage} matches={byStage[activeStage] ?? []} />
    </div>
  );
}

function StageBracket({ stage, matches }: { stage: string; matches: Match[] }) {
  const expected = KNOCKOUT_EXPECTED_COUNTS[stage] ?? matches.length;
  const slots = Array.from({ length: expected }, (_, index) => matches[index] ?? null);
  const leftSlots = slots.slice(0, Math.ceil(slots.length / 2));
  const rightSlots = slots.slice(Math.ceil(slots.length / 2));
  const completedCount = matches.filter(isFinishedWithScore).length;

  if (expected <= 1) {
    return (
      <div className="stageBracketCanvas stageBracketCanvas--single">
        <div className="stageBracketTitle">
          <strong>{stageLabel(stage)}</strong>
          <span>{completedCount}/{expected} 场已完赛</span>
        </div>
        <div className="stageBracketSingleNode">
          <BracketMatchNode match={slots[0] ?? null} index={0} />
        </div>
      </div>
    );
  }

  return (
    <div className="stageBracketCanvas">
      <div className="stageBracketSide">
        {leftSlots.map((match, index) => (
          <BracketMatchNode key={match?.match_id ?? `${stage}-left-${index}`} match={match} index={index} />
        ))}
      </div>
      <div className="stageBracketCenter">
        <span className="stageBracketLine" />
        <div className="stageBracketTitle">
          <strong>{stageLabel(stage)}</strong>
          <span>{completedCount}/{expected} 场已完赛</span>
        </div>
        <span className="stageBracketLine" />
      </div>
      <div className="stageBracketSide stageBracketSide--right">
        {rightSlots.map((match, index) => (
          <BracketMatchNode key={match?.match_id ?? `${stage}-right-${index}`} match={match} index={leftSlots.length + index} />
        ))}
      </div>
    </div>
  );
}

function BracketMatchNode({ match, index }: { match: Match | null; index: number }) {
  if (!match) {
    return (
      <div className="bracketNode bracketNode--placeholder">
        <div className="bracketNodeMeta">
          <Tag>未确定</Tag>
          <span>第 {index + 1} 场</span>
        </div>
        <div className="bracketTeams">
          <strong>待定</strong>
          <span>vs</span>
          <strong>待定</strong>
        </div>
        <small>还未比赛</small>
      </div>
    );
  }

  return (
    <div className={`bracketNode ${match.status === "finished" ? "bracketNode--finished" : ""}`}>
      <div className="bracketNodeMeta">
        <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
        <span>{formatDate(match.match_date)} {formatTime(match.match_time)}</span>
      </div>
      <div className="bracketTeams">
        <strong>{displayTeamName(match.home_team_name)}</strong>
        <span className="bracketScore">{displayScore(match)}</span>
        <strong>{displayTeamName(match.away_team_name)}</strong>
      </div>
      <small>{match.venue || "比赛场地待定"}</small>
    </div>
  );
}

function ResultsPage() {
  const cachedMatches = getCachedMatches();
  const [matches, setMatches] = useState<Match[]>(cachedMatches ?? []);

  const refreshMatches = async () => {
    setMatches(await getMatches({ forceRefresh: true }));
  };

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
      <LiveSyncBar onRefresh={refreshMatches} />
      <PageTitle title="比赛结果概览" sub="已完赛显示数据库真实比分；赛果待同步的比赛可通过实时刷新或后台调度更新。" />
      <div className="matchList">
        {matches.map((match) => (
          <div className="matchRow" key={match.match_id}>
            <div className="matchMeta">
              <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
              <Tag>{stageLabel(match.stage, match.stage_number)}</Tag>
              <span>{match.match_date}</span>
            </div>
            <div className="teamsLine">
              <strong>{displayTeamName(match.home_team_name)}</strong>
              <span>{displayScore(match)}</span>
              <strong>{displayTeamName(match.away_team_name)}</strong>
            </div>
            {match.saved_prediction && (
              <div className="savedPredictionLine">
                <Tag color="blue">已保存预测</Tag>
                <span>
                  预测 {match.saved_prediction.predicted_home_score}-{match.saved_prediction.predicted_away_score}
                </span>
                {match.saved_prediction.created_at && <small>{new Date(match.saved_prediction.created_at).toLocaleString("zh-CN")}</small>}
              </div>
            )}
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
