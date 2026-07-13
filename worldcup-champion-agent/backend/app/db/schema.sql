-- ============================================================
-- 世界杯冠军预测 Agent —— PostgreSQL 建表脚本
-- 仅结构化数据（不含向量库 / 知识库，语义检索另行处理）
--
-- 设计要点：
--   1. 慢变量画像用 as_of 快照，只 INSERT 不 UPDATE，可算趋势 / 可回溯
--   2. 名单型数据（伤病 / 首发 / 天气）用 JSONB 列
--   3. 单场情报用 UNIQUE(match_id, team_id) + ON CONFLICT 刷新
--   4. 预测结果记录所用情报版本（stats_as_of / pre_match_intel_id）保证可复现
--   5. 时间统一使用 TIMESTAMPTZ
-- ============================================================

-- ---------- 1. 球队静态维度 ----------
CREATE TABLE teams (
    team_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    "group"       TEXT,
    country_code  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- 2. 球队慢变量画像（2 号侦察写，版本化，不覆盖）----------
CREATE TABLE team_stats_snapshots (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_id            TEXT NOT NULL REFERENCES teams(team_id),
    as_of              TIMESTAMPTZ NOT NULL,          -- 数据截止时间（核心字段）
    fifa_rank          INT,
    elo_rating         REAL,
    rank_change_30d    INT,
    elo_change_30d     REAL,
    recent_matches_n   INT,
    avg_goals_for      REAL,
    avg_goals_against  REAL,
    recent_form        REAL,
    attack_score       REAL,
    defense_score      REAL,
    xg_for             REAL,
    xg_against         REAL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_team_stats_latest ON team_stats_snapshots (team_id, as_of DESC);

-- ---------- 3. 赛前实时情报（1 号侦察写，绑定单场，可 upsert 刷新）----------
CREATE TABLE pre_match_intel (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id           TEXT NOT NULL,
    team_id            TEXT NOT NULL REFERENCES teams(team_id),
    as_of              TIMESTAMPTZ NOT NULL,
    squad_availability REAL,
    injuries           JSONB,   -- [{"player":"Neymar","status":"doubtful","impact":"high"}]
    suspensions        JSONB,
    expected_lineup    JSONB,   -- 预计首发 11 人
    rotation_risk      TEXT,    -- low / medium / high
    key_players_out    JSONB,
    weather            JSONB,
    confidence         TEXT DEFAULT 'medium',
    sources            TEXT[],
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, team_id)
);

-- ---------- 4. 赛程 ----------
CREATE TABLE matches (
    match_id      TEXT PRIMARY KEY,
    stage         TEXT NOT NULL,           -- group / quarter / semi / final
    "group"       TEXT,
    round_number  INT,                     -- 小组赛第几轮
    home_team_id  TEXT REFERENCES teams(team_id),
    away_team_id  TEXT REFERENCES teams(team_id),
    match_time    TIMESTAMPTZ,
    venue         TEXT
);

-- ---------- 5. 侦察审计（1 号 + 2 号都写）----------
CREATE TABLE scout_findings (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scout_agent  TEXT NOT NULL,            -- ScoutAgent1 / ScoutAgent2
    trigger      TEXT NOT NULL,            -- pre_match / post_review / scheduled
    run_id       TEXT,
    match_id     TEXT,
    team_id      TEXT,
    query        TEXT,
    sources      TEXT[],
    findings     JSONB,
    confidence   TEXT,
    latency_ms   INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_scout_findings_match ON scout_findings (match_id, scout_agent);

-- ---------- 6. 预测任务元数据 ----------
CREATE TABLE prediction_runs (
    run_id            TEXT PRIMARY KEY,
    mode              TEXT,                -- full / ratings / group / knockout / champion
    monte_carlo_runs  INT,
    llm_enabled       BOOLEAN,
    llm_model         TEXT,
    status            TEXT,                -- running / completed / failed / canceled
    final_champion    TEXT,
    verifier_passed   BOOLEAN,
    duration_ms       INT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- 7. 单场预测结果（记录所用情报版本，保证可复现）----------
CREATE TABLE predicted_matches (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                TEXT REFERENCES prediction_runs(run_id),
    match_id              TEXT NOT NULL,
    stage                 TEXT,
    home_team_id          TEXT,
    away_team_id          TEXT,
    predicted_home_score  INT,
    predicted_away_score  INT,
    home_win_prob         REAL,
    draw_prob             REAL,
    away_win_prob         REAL,
    winner                TEXT,
    confidence            REAL,
    explanation           TEXT,
    critic_passed         BOOLEAN,
    pre_match_intel_id    BIGINT REFERENCES pre_match_intel(id),  -- 本次所用赛前情报
    home_stats_as_of      TIMESTAMPTZ,     -- 所用主队慢变量画像版本
    away_stats_as_of      TIMESTAMPTZ,     -- 所用客队慢变量画像版本
    top_scores            JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pred_match_run ON predicted_matches (run_id, match_id);

-- ---------- 8. 冠军概率 ----------
CREATE TABLE champion_probabilities (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       TEXT REFERENCES prediction_runs(run_id),
    team_id      TEXT,
    probability  REAL,
    rank         INT
);
CREATE INDEX idx_champion_prob_run ON champion_probabilities (run_id);

-- ---------- 9. 各轮到达概率 ----------
CREATE TABLE round_reach_probabilities (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       TEXT REFERENCES prediction_runs(run_id),
    team_id      TEXT,
    round_name   TEXT,          -- quarter / semi / final / champion
    probability  REAL
);
CREATE INDEX idx_round_reach_run ON round_reach_probabilities (run_id);

-- ---------- 10. 小组积分榜 ----------
CREATE TABLE group_standings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          TEXT REFERENCES prediction_runs(run_id),
    "group"         TEXT,
    team_id         TEXT,
    rank            INT,
    points          INT,
    goals_for       INT,
    goals_against   INT,
    goal_difference INT,
    qualified       BOOLEAN,
    third_rank      INT           -- 小组第三专用排名，非第三则 NULL
);
CREATE INDEX idx_group_standings_run ON group_standings (run_id, "group");
