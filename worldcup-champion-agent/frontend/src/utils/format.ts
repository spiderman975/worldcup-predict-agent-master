export const percent = (value?: number) => `${(((value ?? 0) as number) * 100).toFixed(1)}%`;

export const stageName = (stage: string) => {
  const names: Record<string, string> = {
    group: "小组赛",
    round_of_32: "1/16决赛（32强）",
    round_of_16: "1/8决赛（16强）",
    quarter: "1/4决赛",
    semi: "半决赛",
    final: "决赛",
    third_place: "三四名决赛",
  };
  return names[stage] ?? stage;
};
