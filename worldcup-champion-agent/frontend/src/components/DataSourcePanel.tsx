import { Card, Descriptions } from "antd";

export function DataSourcePanel() {
  return (
    <Card title="数据来源与模型说明" className="panel">
      <Descriptions size="small" column={1}>
        <Descriptions.Item label="球队数据">local demo teams.json</Descriptions.Item>
        <Descriptions.Item label="赛程数据">local demo matches_2026.json</Descriptions.Item>
        <Descriptions.Item label="特征数据">local generated team_features.json</Descriptions.Item>
        <Descriptions.Item label="单场模型">0-5 球 Poisson 比分概率矩阵</Descriptions.Item>
        <Descriptions.Item label="冠军概率">Monte Carlo 锦标赛模拟</Descriptions.Item>
        <Descriptions.Item label="扩展方向">football-data、Kaggle、Wikipedia、FIFA 排名和网页搜索</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}
