import { Button, InputNumber, Space, Switch, Tag } from "antd";
import { PlayCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { useState } from "react";

import { usePredictionStore } from "../stores/predictionStore";

export function PredictionControl() {
  const [runs, setRuns] = useState(1000);
  const [search, setSearch] = useState(false);
  const { startRun, reset, status, currentPhase, currentRunId } = usePredictionStore();
  const running = status === "pending" || status === "running";

  return (
    <div className="controlBar">
      <Space wrap>
        <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={() => startRun(runs, search)}>
          开始预测
        </Button>
        <Button icon={<ReloadOutlined />} onClick={reset}>
          重置
        </Button>
        <InputNumber min={100} max={10000} step={100} value={runs} onChange={(value) => setRuns(value ?? 1000)} addonBefore="模拟次数" />
        <Space>
          <span>实时搜索</span>
          <Switch checked={search} onChange={setSearch} />
        </Space>
        <Tag color={status === "completed" ? "green" : running ? "blue" : status === "failed" ? "red" : "default"}>{status}</Tag>
        <Tag>{currentPhase}</Tag>
        {currentRunId ? <Tag color="purple">{currentRunId.slice(0, 8)}</Tag> : null}
      </Space>
    </div>
  );
}
