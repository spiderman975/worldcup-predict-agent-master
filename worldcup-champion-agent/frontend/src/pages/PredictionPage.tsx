import { useState } from "react";
import { Button, Layout } from "antd";
import { MessageOutlined } from "@ant-design/icons";

import { Bracket } from "../components/Bracket";
import { ChampionProb } from "../components/ChampionProb";
import { ChatPanel } from "../components/ChatPanel";
import { DataSourcePanel } from "../components/DataSourcePanel";
import { GroupStagePanel } from "../components/GroupStagePanel";
import { MatchDetail } from "../components/MatchDetail";
import { PredictionControl } from "../components/PredictionControl";
import { PredictionProgress } from "../components/PredictionProgress";
import { ReasoningPanel } from "../components/ReasoningPanel";

export function PredictionPage() {
  const [chatVisible, setChatVisible] = useState(false);

  return (
    <Layout className="appShell">
      <header className="topHeader">
        <div>
          <h1>世界杯冠军预测 Agent</h1>
          <p>FastAPI + React 的可解释预测 MVP</p>
        </div>
        <div className="headerActions">
          <Button icon={<MessageOutlined />} onClick={() => setChatVisible(true)} type="primary" ghost>
            Agent 对话
          </Button>
          <PredictionControl />
        </div>
      </header>
      <main className="mainGrid">
        <section className="progressBand">
          <PredictionProgress />
        </section>
        <section className="leftPane">
          <GroupStagePanel />
        </section>
        <section className="centerPane">
          <Bracket />
          <MatchDetail />
        </section>
        <section className="rightPane">
          <ChampionProb />
          <ReasoningPanel />
        </section>
        <section className="bottomBand">
          <DataSourcePanel />
        </section>
      </main>
      {!chatVisible && (
        <Button
          className="chatFloatBtn"
          type="primary"
          shape="circle"
          size="large"
          icon={<MessageOutlined />}
          onClick={() => setChatVisible(true)}
        />
      )}
      <ChatPanel visible={chatVisible} onClose={() => setChatVisible(false)} />
    </Layout>
  );
}
