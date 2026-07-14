/* ════════════════════════════════════════════════════════════
   Pipeline stages & mock data — Cerno 视频分析工作台
   ════════════════════════════════════════════════════════════ */

export interface PipelineStage {
  id: string;
  label: string;
  description: string;
  icon: "qc" | "segment" | "align" | "caption" | "embed" | "summary";
  progressStart: number;  // total_progress range start
  progressEnd: number;    // total_progress range end
}

/* ── Pipeline 各阶段（与后端 status_tracker PHASE_WEIGHTS 对齐） ── */

export const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: "qc",
    label: "质量检测",
    description: "视频完整性验证中",
    icon: "qc",
    progressStart: 0.00,
    progressEnd: 0.10,
  },
  {
    id: "segment",
    label: "场景分割",
    description: "镜头边界检测中",
    icon: "segment",
    progressStart: 0.15,
    progressEnd: 0.20,
  },
  {
    id: "align",
    label: "模态对齐",
    description: "时间戳分配到场景中",
    icon: "align",
    progressStart: 0.40,
    progressEnd: 0.50,
  },
  {
    id: "caption",
    label: "深度理解",
    description: "VLM 画面描述中",
    icon: "caption",
    progressStart: 0.50,
    progressEnd: 0.75,
  },
  {
    id: "embed",
    label: "向量编码",
    description: "2048 维向量生成中",
    icon: "embed",
    progressStart: 0.75,
    progressEnd: 0.85,
  },
  {
    id: "summary",
    label: "摘要生成",
    description: "结构化摘要生成中",
    icon: "summary",
    progressStart: 0.85,
    progressEnd: 1.00,
  },
];

/* ── 根据 total_progress 计算当前阶段索引 ── */

export function getCurrentStageIndex(progress: number): number {
  for (let i = PIPELINE_STAGES.length - 1; i >= 0; i--) {
    if (progress >= PIPELINE_STAGES[i].progressStart) {
      return i;
    }
  }
  return 0;
}

/* ── 计算阶段内进度（0~1） ── */

export function getStageInternalProgress(progress: number, stage: PipelineStage): number {
  if (progress <= stage.progressStart) return 0;
  if (progress >= stage.progressEnd) return 1;
  return (progress - stage.progressStart) / (stage.progressEnd - stage.progressStart);
}

/* ── 获取滑动窗口的三张卡片 ── */

export function getWindowCards(currentIndex: number) {
  // 已完成：currentIndex - 1（正在滑出左）
  // 进行中：currentIndex
  // 等待中：currentIndex + 1（即将从右滑入）
  const cards = [];

  if (currentIndex > 0) {
    cards.push({ ...PIPELINE_STAGES[currentIndex - 1], cardStatus: "completed" as const });
  }
  cards.push({ ...PIPELINE_STAGES[currentIndex], cardStatus: "in_progress" as const });
  if (currentIndex < PIPELINE_STAGES.length - 1) {
    cards.push({ ...PIPELINE_STAGES[currentIndex + 1], cardStatus: "pending" as const });
  }

  return cards;
}
