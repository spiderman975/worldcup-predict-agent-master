import {
  ApartmentOutlined,
  CalendarOutlined,
  HomeOutlined,
  MessageOutlined,
  ReadOutlined,
  TeamOutlined,
  TrophyOutlined,
} from "@ant-design/icons";
import { Alert, Button, ConfigProvider, Empty, Layout, Menu, Modal, Progress, Spin, Table, Tag, message, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useEffect, useState } from "react";
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
  predictMatch,
  triggerLiveSync,
  type LiveSyncStatus,
  type Match,
  type Team,
  type TeamMember,
} from "./api/predictionApi";
import { ChatPanel } from "./components/ChatPanel";
import { ScheduleKnockoutPage } from "./pages/ScheduleKnockoutPage";
import { stageName } from "./utils/format";

type Rating = {
  team_id: string;
  name: string;
  overall_rating: number;
  attack_strength: number;
  defense_strength: number;
};

const QUIET_REFRESH_MS = 3 * 60 * 1000;

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
  return match.status === "scheduled" || match.status === "live";
}

function isWithinPrematchWindow(match: Match, now = new Date()) {
  const time = new Date(match.match_time).getTime();
  if (!Number.isFinite(time)) return false;
  const diff = time - now.getTime();
  return diff >= 0 && diff <= 30 * 60 * 1000;
}

function liveSyncText(status?: LiveSyncStatus | null) {
  if (!status) return "使用本地数据库数据";
  if (status.running) return "正在同步";
  if (status.status === "missing_api_key") return "未配置实时比分 API";
  if (status.status === "failed") return "最近同步失败";
  if (status.status === "success") return "实时数据已更新";
  return "使用本地数据库数据";
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
            { key: "/knockout", icon: <ApartmentOutlined />, label: <Link to="/knockout">淘汰赛对阵</Link> },
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
          <Route path="/knockout" element={<ScheduleKnockoutPage />} />
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
        <div>
          <Tag color="blue">2026 database schedule</Tag>
          <h1>世界杯比赛预测主系统</h1>
          <p>
            以数据库赛程为轴组织赛程、球队与单场预测。Chat Agent 负责理解你的问题，并在需要时启动单场多 Agent 工作流。
          </p>
        </div>
        <div className="newsRail">
          <Link className="newsCard newsCard--action" to="/schedule?view=prematch">
            <ReadOutlined /> 赛前 30 分钟：实时信息增强预测入口
          </Link>
          <Link className="newsCard newsCard--action" to="/schedule?view=manual">
            <CalendarOutlined /> 手动按钮：基于历史实力执行单场预测
          </Link>
          <Link className="newsCard newsCard--action" to="/results">
            <TrophyOutlined /> 赛后视图：展示真实比分与已保存理由
          </Link>
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
  const [predicting, setPredicting] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
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
      refreshSchedule().catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const allMatches = dates.flatMap((day) => day.matches);
  const today = beijingDateString();
  const todayMatches = dates.find((day) => day.date === today)?.matches ?? [];
  const nextDay = dates.find((day) => day.date > today);
  const futurePredictable = allMatches.filter((match) => isPredictable(match) && new Date(match.match_time).getTime() >= Date.now());
  const prematchMatches = futurePredictable.filter((match) => isWithinPrematchWindow(match));
  const nextFutureMatch = futurePredictable[0];

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

  if (loading) return <LoadingState text="正在加载赛程..." />;
  return (
    <div className="pageStack">
      <PageTitle title="世界杯赛程表" sub="点击比赛日查看当日对阵。已完赛日期会以绿色标注，赛程数据优先来自 SQLite 数据库。" />
      <LiveSyncBar onRefresh={refreshSchedule} />
      {todayMatches.length === 0 && (
        <Alert
          type="info"
          showIcon
          message="今天没有世界杯比赛。"
          description={nextDay ? `下一比赛日：${formatDate(nextDay.date)}，共 ${nextDay.matches.length} 场。` : "当前赛程中没有未来比赛日。"}
          action={nextDay ? <Button size="small" onClick={() => navigate(`/schedule/${nextDay.date}`)}>查看下一比赛日</Button> : undefined}
        />
      )}
      {view === "prematch" && (
        <section className="focusPanel">
          <h2>赛前 30 分钟实时增强预测</h2>
          {prematchMatches.length === 0 ? (
            <Alert
              type="info"
              showIcon
              message="当前 30 分钟内没有即将开始的比赛。"
              description={nextFutureMatch ? `最近一场未来比赛：${formatDate(nextFutureMatch.match_date)} ${formatTime(nextFutureMatch.match_time)}，${nextFutureMatch.home_team_name} vs ${nextFutureMatch.away_team_name}` : "当前没有可预测的未来比赛。"}
              action={nextFutureMatch ? <Button onClick={() => navigate(`/schedule/${nextFutureMatch.match_date}`)}>查看下一场比赛</Button> : undefined}
            />
          ) : (
            <div className="matchList">
              {prematchMatches.map((match) => (
                <div className="matchRow matchRow--highlight" key={match.match_id}>
                  <div className="matchMeta">
                    <Tag color="blue">{stageName(match.stage, match.stage_number)}</Tag>
                    <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
                    <span>{formatDate(match.match_date)} {formatTime(match.match_time)}</span>
                  </div>
                  <div className="teamsLine"><strong>{match.home_team_name}</strong><span>vs</span><strong>{match.away_team_name}</strong></div>
                  <Button type="primary" loading={predicting === match.match_id} onClick={() => handlePredict(match, true)}>实时增强预测</Button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
      {view === "manual" && (
        <section className="focusPanel">
          <h2>未来比赛手动预测</h2>
          {futurePredictable.length === 0 ? <Empty description="当前没有可预测的未来比赛" /> : (
            <div className="matchList">
              {futurePredictable.map((match) => (
                <div className="matchRow" key={match.match_id}>
                  <div className="matchMeta">
                    <Tag color="blue">{stageName(match.stage, match.stage_number)}</Tag>
                    <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
                    <span>{formatDate(match.match_date)} {formatTime(match.match_time)}</span>
                  </div>
                  <div className="teamsLine"><strong>{match.home_team_name}</strong><span>vs</span><strong>{match.away_team_name}</strong></div>
                  <Button type="primary" loading={predicting === match.match_id} onClick={() => handlePredict(match, false)}>预测比分</Button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
      <div className="calendarGrid">
        {dates.map((day) => {
          const finished = day.matches.length > 0 && day.matches.every((match) => match.status === "finished");
          const pending = day.matches.some((match) => match.status === "result_pending");
          const isToday = day.date === today;
          const finishedCount = day.matches.filter((match) => match.status === "finished").length;
          return (
            <button
              key={day.date}
              className={`dateTile ${finished ? "dateTile--finished" : ""} ${pending ? "dateTile--pending" : ""} ${isToday ? "dateTile--today" : ""}`}
              onClick={() => navigate(`/schedule/${day.date}`)}
            >
              <span>{formatDate(day.date)}</span>
              <strong>{day.matches.length} 场</strong>
              <small>{isToday ? "今日" : pending ? "赛果待同步" : finished ? "已完赛" : `${finishedCount} 场已完赛`}</small>
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
  const [refreshing, setRefreshing] = useState(false);
  const [prediction, setPrediction] = useState<any | null>(null);

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
    try {
      setPrediction(await predictMatch(matchId, { realtime: false }));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "预测失败");
    } finally {
      setPredicting(null);
    }
  };

  const refreshResults = async () => {
    setRefreshing(true);
    try {
      const result = await triggerLiveSync();
      if (result.status === "missing_api_key") message.warning(result.message || "未配置实时比分 API。");
      const items = await getMatches({ forceRefresh: true });
      setMatches(items.filter((match) => match.match_date === date));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "刷新赛果失败");
    } finally {
      setRefreshing(false);
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
              <Tag color="blue">{stageName(match.stage, match.stage_number)}</Tag>
              <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
              <span>{formatTime(match.match_time)}</span>
              {match.venue && <span>{match.venue}</span>}
            </div>
            <div className="teamsLine">
              <strong>{match.home_team_name}</strong>
              <span>{displayScore(match)}</span>
              <strong>{match.away_team_name}</strong>
            </div>
            {match.status === "finished" ? (
              <Tag color="green">已完赛 {match.actual_home_score}-{match.actual_away_score}</Tag>
            ) : match.status === "result_pending" ? (
              <Button loading={refreshing} onClick={refreshResults}>刷新赛果</Button>
            ) : !isPredictable(match) ? (
              <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
            ) : (
              <Button type="primary" loading={predicting === match.match_id} onClick={() => handlePredict(match.match_id)}>
                预测比赛结果
              </Button>
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
  const explanation = record.explanation ?? pred?.explanation;
  return (
    <div className="predictionSummary">
      <h3>{record.match.home_team_name} vs {record.match.away_team_name}</h3>
      <div className="scoreLine">{pred.predicted_home_score} - {pred.predicted_away_score}</div>
      <p>{explanation}</p>
      <div className="matchMeta">
        <Tag color={record.mode === "realtime" ? "red" : "blue"}>{record.mode === "realtime" ? "实时增强" : "历史实力"}</Tag>
        {record.created_at && <span>{new Date(record.created_at).toLocaleString("zh-CN")}</span>}
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
  const [team, setTeam] = useState<Team | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!teamId) return;
    setLoading(true);
    setError(null);
    getTeamDetail(teamId)
      .then((detail) => {
        setTeam(detail);
        setMembers(detail.members ?? []);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "球队详情加载失败");
      })
      .finally(() => setLoading(false));
  }, [teamId]);

  if (loading) return <LoadingState text="正在加载球队详情..." />;
  if (error) return <Alert type="error" showIcon message="球队详情加载失败" description={error} />;
  if (!team) return <Empty description="球队不存在" />;
  return (
    <div className="pageStack">
      <PageTitle title={team.name} sub={`${team.group} 组，FIFA 排名 ${team.fifa_rank}`} />
      <div className="detailPanel">
        <Progress percent={Math.round(team.attack_score * 100)} format={(v) => `进攻 ${v}%`} />
        <Progress percent={Math.round(team.defense_score * 100)} format={(v) => `防守 ${v}%`} />
        <Progress percent={Math.round(team.recent_form * 100)} format={(v) => `状态 ${v}%`} />
      </div>
      <div className="detailPanel">
        <h2 className="sectionTitle">球员阵容</h2>
        {members.length === 0 ? (
          <Empty description="接口未返回球员信息" />
        ) : (
          <Table<TeamMember>
            rowKey="name"
            dataSource={members}
            pagination={members.length > 30 ? { pageSize: 30 } : false}
            columns={[
              { title: "球员姓名", dataIndex: "name" },
              {
                title: "阵容状态",
                dataIndex: "is_starting",
                render: (value: boolean) => <Tag color={value ? "green" : "default"}>{value ? "首发" : "替补"}</Tag>,
                filters: [
                  { text: "首发", value: true },
                  { text: "替补", value: false },
                ],
                onFilter: (value, record) => record.is_starting === value,
              },
              {
                title: "进攻评分",
                dataIndex: "attack",
                sorter: (a, b) => a.attack - b.attack,
                render: (value: number) => value.toFixed(1),
              },
              {
                title: "防守评分",
                dataIndex: "defensive",
                sorter: (a, b) => a.defensive - b.defensive,
                render: (value: number) => value.toFixed(1),
              },
              {
                title: "健康状态",
                dataIndex: "injured",
                render: (value: boolean) => <Tag color={value ? "red" : "blue"}>{value ? "伤病" : "正常"}</Tag>,
              },
              {
                title: "伤病说明",
                dataIndex: "injury_description",
                render: (value: string) => value || "无",
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}

function ResultsPage() {
  const cachedMatches = getCachedMatches();
  const [matches, setMatches] = useState<Match[]>(cachedMatches ?? []);

  const refreshMatches = async () => {
    const items = await getMatches({ forceRefresh: true });
    setMatches(items);
  };

  useEffect(() => {
    getMatches().then(setMatches);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshMatches().catch(() => undefined);
    }, QUIET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="pageStack">
      <PageTitle title="比赛结果概览" sub="已完赛显示数据库真实比分；未赛比赛可通过赛程页或 Chat Agent 生成并保存预测。" />
      <LiveSyncBar onRefresh={refreshMatches} />
      <div className="matchList">
        {matches.map((match) => (
          <div className="matchRow" key={match.match_id}>
            <div className="matchMeta">
              <Tag color="blue">{stageName(match.stage, match.stage_number)}</Tag>
              <Tag color={matchStatusColor(match.status)}>{matchStatusText(match.status)}</Tag>
              <span>{match.match_date}</span>
            </div>
            <div className="teamsLine">
              <strong>{match.home_team_name}</strong>
              <span>{displayScore(match)}</span>
              <strong>{match.away_team_name}</strong>
            </div>
            {match.saved_prediction && (
              <div className="savedPredictionLine">
                预测 {match.saved_prediction.predicted_home_score}-{match.saved_prediction.predicted_away_score}
                <Tag color={match.saved_prediction.mode === "realtime" ? "red" : "blue"}>
                  {match.saved_prediction.mode === "realtime" ? "实时增强" : "历史实力"}
                </Tag>
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
