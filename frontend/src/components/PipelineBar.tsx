/* ════════════════════════════════════════════════════════════
   PipelineBar — extracted from Dashboard.tsx
   ════════════════════════════════════════════════════════════ */

import { useMemo } from "react";
import { computePipelineStages } from "../mockData";
import type { PipelineStage, PipelineSwitches } from "../mockData";


const stageColorMap: Record<string, string> = {
  qc:       "#4785f0",
  segment:  "#4f93ed",
  keyframe: "#5799e9",
  audio:    "#5ca8e8",
  align:    "#63b4e0",
  caption:  "#67c4c0",
  embed:    "#60c9a8",
  summary:  "#55c890",
};

export function PipelineBar({
  progress,
  statusDetail,
  switches,
  subtitle,
}: {
  progress: number;
  statusDetail?: string | null;
  switches: PipelineSwitches;
  subtitle?: string | null;
}) {
  const stages = useMemo(() => computePipelineStages(switches), [switches]);
  const isEmpty = progress === 0 && !subtitle;
  const isComplete = progress >= 1;

  const statusText = subtitle || (
    isEmpty
      ? "选择视频后查看处理进度"
      : isComplete
        ? "处理完成 ✓"
        : (statusDetail || "处理中...")
  );

  return (
    <div className="card-surface rounded-2xl px-5 py-4 border border-gray-200/60 w-full flex flex-col gap-y-2.5">
      {/* ── Row 1: Progress bar ── */}
      <div>
        <div className="relative h-5 w-full rounded-full overflow-hidden bg-gray-100/50">
          <div
            className="absolute inset-0 rounded-full transition-all duration-700 ease-out"
            style={{
              background: "linear-gradient(90deg, #4785f0 0%, #4f93ed 20%, #5ca8e8 40%, #67c4c0 60%, #60c9a8 80%, #55c890 100%)",
              clipPath: `inset(0 ${100 - Math.round(progress * 100)}% 0 0)`,
              transition: "clip-path 700ms ease-out",
            }}
          />
        </div>
      </div>

      {/* ── Row 2: Stage pills (dynamic) ── */}
      <div className="flex items-center justify-between flex-wrap gap-x-3 gap-y-1">
        {stages.map((stage) => {
          const isDone = progress >= stage.progressEnd;
          const isActive = !isDone && progress >= stage.progressStart;
          const c = stageColorMap[stage.id] || "#4785f0";

          return (
            <div key={stage.id} className="flex items-center gap-1.5">
              {isDone ? (
                <div className="w-[18px] h-[18px] rounded-full bg-green-400 flex items-center justify-center flex-shrink-0">
                  <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" strokeWidth="3" stroke="currentColor">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
              ) : isActive ? (
                <div
                  className="w-[18px] h-[18px] rounded-full flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: c }}
                >
                  <div className="w-2 h-2 rounded-full bg-white" />
                </div>
              ) : (
                <div className="w-[18px] h-[18px] rounded-full bg-gray-200/70 flex-shrink-0" />
              )}
              <span
                className={`text-xs font-medium whitespace-nowrap ${
                  isDone ? "text-gray-700" : isActive ? "text-gray-900" : "text-gray-400"
                }`}
              >
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* ── Row 3: Status line ── */}
      {statusText && (
        <p
          className={`text-[11px] ${
            isComplete ? "text-green-500 font-medium" : "text-gray-500"
          }`}
        >
          {statusText}
        </p>
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   VideoSummaryCard — 连接后端 API
   ════════════════════════════════════════════════════════════ */

