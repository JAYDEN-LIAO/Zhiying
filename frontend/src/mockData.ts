/* ════════════════════════════════════════════════════════════
   Pipeline stages & mock data — Cerno 视频分析工作台 (v0.8)
   阶段节点从后端 GET /api/v1/pipeline/operations 动态获取，
   不再在前端重复 gate 逻辑。
   ════════════════════════════════════════════════════════════ */

export type StageIcon = "upload" | "segment" | "keyframe" | "audio" | "align" | "caption" | "embed" | "summary";

export interface PipelineStage {
  id: StageIcon | string;
  label: string;
  description: string;
  progressStart: number;
  progressEnd: number;
}

/* ── v0.8: 从后端 API 获取（推荐）── */

export interface PipelineOperation {
  name: string;
  label: string;
  description: string;
  progress_start: number;
  progress_end: number;
}

export async function fetchPipelineStages(videoId: string): Promise<PipelineStage[]> {
  const res = await fetch(`/api/v1/pipeline/operations?video_id=${videoId}`);
  const json = await res.json();
  const ops: PipelineOperation[] = json.data ?? [];
  return ops.map((op) => ({
    id: op.name,
    label: op.label,
    description: op.description,
    progressStart: op.progress_start,
    progressEnd: op.progress_end,
  }));
}

/* ── 根据参数动态计算阶段列表 + 进度区间 ── */

export interface PipelineSwitches {
  vision_enabled: boolean;
  audio_enabled: boolean;
  caption_enabled: boolean;
  search_index_enabled: boolean;
  summary_enabled: boolean;
}

export function computePipelineStages(switches: PipelineSwitches): PipelineStage[] {
  const stages: PipelineStage[] = [];

  // 1. 视频上传 (始终)
  stages.push({ id: "upload", label: "视频上传", description: "视频文件上传中", progressStart: 0.0, progressEnd: 0.10 });

  // 2. 镜头分割 (始终)
  stages.push({ id: "segment", label: "场景分割", description: "镜头边界检测中", progressStart: 0.10, progressEnd: 0.15 });

  // 3. 关键帧抽取 (vision)
  if (switches.vision_enabled) {
    stages.push({ id: "keyframe", label: "关键帧抽取", description: "1fps 帧池提取中", progressStart: 0.15, progressEnd: 0.25 });
  }

  // 4. 音频转录 (audio)
  if (switches.audio_enabled) {
    stages.push({ id: "audio", label: "音频转录", description: "语音转文字中", progressStart: 0.25, progressEnd: 0.35 });
  }

  // 5. 文本对齐 (audio)
  if (switches.audio_enabled) {
    stages.push({ id: "align", label: "模态对齐", description: "时间戳分配到场景中", progressStart: 0.35, progressEnd: 0.45 });
  }

  // 6. 画面描述 (vision + caption)
  if (switches.vision_enabled && switches.caption_enabled) {
    stages.push({ id: "caption", label: "画面描述", description: "VLM 画面描述中", progressStart: 0.45, progressEnd: 0.65 });
  }

  // 7. 建立索引 (search_index + vision)
  if (switches.search_index_enabled && switches.vision_enabled) {
    stages.push({ id: "embed", label: "建立索引", description: "3-path 向量编码中", progressStart: 0.65, progressEnd: 0.85 });
  }

  // 8. 智能摘要 (summary + caption)
  if (switches.summary_enabled && switches.caption_enabled) {
    stages.push({ id: "summary", label: "智能摘要", description: "结构化摘要生成中", progressStart: 0.85, progressEnd: 1.00 });
  }

  // 重新均匀分配进度区间
  if (stages.length > 0) {
    const step = 1.0 / stages.length;
    stages.forEach((s, i) => {
      s.progressStart = +(i * step).toFixed(2);
      s.progressEnd = +((i + 1) * step).toFixed(2);
    });
    // 最后一个阶段结束于 1.00
    stages[stages.length - 1].progressEnd = 1.0;
  }

  return stages;
}

/* ── 根据 total_progress 计算当前阶段索引 ── */

export function getCurrentStageIndex(stages: PipelineStage[], progress: number): number {
  for (let i = stages.length - 1; i >= 0; i--) {
    if (progress >= stages[i].progressStart) {
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
