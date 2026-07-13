import { Button } from "antd";
import { useNavigate } from "react-router-dom";

export function HomePage() {
  const navigate = useNavigate();
  return (
    <main className="worldcupHero">
      <div className="perspectiveStage">
        <div className="heroCopy">
          <span className="heroKicker">FIFA World Cup 2026</span>
          <h1>世界杯冠军预测 Agent</h1>
          <p>从小组抽签、逐轮赛果、Agent 解释到淘汰赛晋级图，开启一段可解释的预测旅程。</p>
          <Button size="large" type="primary" className="journeyButton" onClick={() => navigate("/journey")}>
            开始世界杯预测之旅
          </Button>
        </div>
      </div>
    </main>
  );
}
