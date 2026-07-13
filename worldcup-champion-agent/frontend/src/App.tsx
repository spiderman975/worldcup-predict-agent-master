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

import { getMatches, getRatings, getSchedule, getTeams, predictMatch } from "./api/predictionApi";
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
    round_of_32: "32 强",
    round_of_16: "16 强",
    quarter: "四分之一决赛",
    semi: "半决赛",
    final: "决赛",
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
  const [dates, setDates] = useState<{ date: string; matches: Match[] }[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    getSchedule().then((res) => setDates(res.dates)).finally(() => setLoading(false));
  }, []);

  if (loading) return <Spin />;
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
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [predicting, setPredicting] = useState<string | null>(null);
  const [prediction, setPrediction] = useState<any | null>(null);

  useEffect(() => {
    getMatches().then((items) => setMatches(items.filter((match) => match.match_date === date))).finally(() => setLoading(false));
  }, [date]);

  const handlePredict = async (matchId: string) => {
    setPredicting(matchId);
    try {
      setPrediction(await predictMatch(matchId));
    } finally {
      setPredicting(null);
    }
  };

  if (loading) return <Spin />;
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
  return (
    <div className="predictionSummary">
      <h3>{record.match.home_team_name} vs {record.match.away_team_name}</h3>
      <div className="scoreLine">{pred.predicted_home_score} - {pred.predicted_away_score}</div>
      <p>{pred.explanation}</p>
      <div className="probGrid">
        <Progress percent={Math.round(pred.home_win_prob * 100)} size="small" format={(v) => `主胜 ${v}%`} />
        <Progress percent={Math.round(pred.draw_prob * 100)} size="small" format={(v) => `平局 ${v}%`} />
        <Progress percent={Math.round(pred.away_win_prob * 100)} size="small" format={(v) => `客胜 ${v}%`} />
      </div>
    </div>
  );
}

function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([getTeams(), getRatings()]).then(([teamItems, ratingRes]) => {
      setTeams(teamItems);
      setRatings(ratingRes.team_ratings ?? {});
    });
  }, []);

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
  const [teams, setTeams] = useState<Team[]>([]);
  const team = useMemo(() => teams.find((item) => item.team_id === teamId), [teams, teamId]);

  useEffect(() => {
    getTeams().then(setTeams);
  }, []);

  if (!team) return <Spin />;
  return (
    <div className="pageStack">
      <PageTitle title={team.name} sub={`${team.group} 组，FIFA 排名 ${team.fifa_rank}`} />
      <div className="detailPanel">
        <Progress percent={Math.round(team.attack_score * 100)} format={(v) => `进攻 ${v}%`} />
        <Progress percent={Math.round(team.defense_score * 100)} format={(v) => `防守 ${v}%`} />
        <Progress percent={Math.round(team.recent_form * 100)} format={(v) => `状态 ${v}%`} />
        <Empty description="数据库阵容和伤病信息已接入，可通过右下角 Chat Agent 查询具体球队报告。" />
      </div>
    </div>
  );
}

function ResultsPage() {
  const [matches, setMatches] = useState<Match[]>([]);

  useEffect(() => {
    getMatches().then(setMatches);
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
