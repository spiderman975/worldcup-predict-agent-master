import ReactECharts from "echarts-for-react";
import { Card, Empty, Tag } from "antd";

import { usePredictionStore } from "../stores/predictionStore";
import { percent } from "../utils/format";

export function ChampionProb() {
  // Zustand v5 的 selector 必须返回稳定引用；切片放到组件内，避免 React 无限更新。
  const allProbabilities = usePredictionStore((state) => state.championProbabilities);
  const probabilities = allProbabilities.slice(0, 8);
  const finalChampion = usePredictionStore((state) => state.finalChampion);
  const option = {
    tooltip: { formatter: (params: { name: string; value: number }) => `${params.name}: ${params.value.toFixed(1)}%` },
    grid: { left: 84, right: 24, top: 24, bottom: 28 },
    xAxis: { type: "value", max: 100 },
    yAxis: { type: "category", data: probabilities.map((item) => item.team_name).reverse() },
    series: [
      {
        type: "bar",
        data: probabilities.map((item) => Number((item.probability * 100).toFixed(1))).reverse(),
        itemStyle: { color: "#2f6fed" },
      },
    ],
  };
  const champion = probabilities.find((item) => item.team_id === finalChampion);
  return (
    <Card title="冠军概率排行榜" className="panel">
      {champion ? <Tag color="gold">最终预测冠军：{champion.team_name} {percent(champion.probability)}</Tag> : null}
      {probabilities.length > 0 ? (
        <ReactECharts option={option} style={{ height: 280 }} />
      ) : (
        <Empty className="emptyBlock" description="等待预测结果生成" />
      )}
    </Card>
  );
}
