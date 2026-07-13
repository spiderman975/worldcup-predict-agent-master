export const percent = (value?: number) => `${(((value ?? 0) as number) * 100).toFixed(1)}%`;

export const stageName = (stage: string) => {
  const names: Record<string, string> = {
    group: "小组赛",
    quarter: "四分之一决赛",
    semi: "半决赛",
    final: "决赛",
  };
  return names[stage] ?? stage;
};
