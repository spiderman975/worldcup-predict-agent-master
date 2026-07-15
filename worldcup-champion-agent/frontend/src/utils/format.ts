export const percent = (value?: number) => `${(((value ?? 0) as number) * 100).toFixed(1)}%`;

export type MatchStage =
  | "group"
  | "round_of_32"
  | "round_of_16"
  | "quarter"
  | "semi"
  | "third_place"
  | "final";

const STAGE_NAMES: Record<MatchStage, string> = {
  group: "小组赛",
  round_of_32: "32 强",
  round_of_16: "16 强",
  quarter: "四分之一决赛",
  semi: "半决赛",
  third_place: "季军赛",
  final: "决赛",
};

const STAGE_ORDERS: Record<MatchStage, number> = {
  group: 1,
  round_of_32: 2,
  round_of_16: 3,
  quarter: 4,
  semi: 5,
  third_place: 6,
  final: 7,
};

export const stageName = (stage?: string | null, stageNumber?: number) => {
  if (stage && stage in STAGE_NAMES) return STAGE_NAMES[stage as MatchStage];
  return stageNumber ? `第 ${stageNumber} 阶段` : stage ?? "未知阶段";
};

export const stageOrder = (stage?: string | null) => {
  if (stage && stage in STAGE_ORDERS) return STAGE_ORDERS[stage as MatchStage];
  return Number.MAX_SAFE_INTEGER;
};

export const isKnockoutStage = (stage?: string | null) =>
  Boolean(stage && stage !== "group" && stage in STAGE_ORDERS);
