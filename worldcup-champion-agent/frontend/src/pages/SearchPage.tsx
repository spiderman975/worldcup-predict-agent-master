import { Button, Card, Input, List, Space, Tabs } from "antd";
import { useState } from "react";

import { searchMatchExplanations, searchTeams } from "../api/predictionApi";

export function SearchPage() {
  const [query, setQuery] = useState("Brazil");
  const [teams, setTeams] = useState<Record<string, unknown>[]>([]);
  const [explanations, setExplanations] = useState<Record<string, unknown>[]>([]);

  const runTeamSearch = async () => {
    const result = await searchTeams(query);
    setTeams(result.results ?? []);
  };
  const runExplanationSearch = async () => {
    const result = await searchMatchExplanations(query);
    setExplanations(result.results ?? []);
  };

  return (
    <Card title="数据库与向量库检索" className="panel">
      <Space.Compact className="searchBar">
        <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入球队、阶段或关键词" />
        <Button type="primary" onClick={runTeamSearch}>检索球队</Button>
        <Button onClick={runExplanationSearch}>检索比赛解释</Button>
      </Space.Compact>
      <Tabs
        items={[
          {
            key: "teams",
            label: "球队数据库",
            children: <List dataSource={teams} renderItem={(item) => <List.Item>{JSON.stringify(item)}</List.Item>} />,
          },
          {
            key: "explanations",
            label: "比赛解释向量库",
            children: <List dataSource={explanations} renderItem={(item) => <List.Item>{String(item.text)}；相似度 {String(item.score)}</List.Item>} />,
          },
        ]}
      />
    </Card>
  );
}
