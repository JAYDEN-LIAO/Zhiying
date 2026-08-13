/* ════════════════════════════════════════════════════════════
   PipelineBar — v2.0 new style (mockup-dark)
   ════════════════════════════════════════════════════════════ */

import type { PipelineStage } from "../types";

export function PipelineBar({
  progress,
  statusDetail,
  stages,
  subtitle,
  dark,
}: {
  progress: number;
  statusDetail?: string | null;
  stages: PipelineStage[];
  subtitle?: string | null;
  dark?: boolean; // 暗色 variant（视频顶部浮层用）
}) {
  const isEmpty = progress === 0 && !subtitle;
  const isComplete = progress >= 1;

  const statusText = subtitle
    || (isEmpty ? "选择视频后查看处理进度" : isComplete ? "处理完成 ✓" : (statusDetail || "处理中..."));

  return (
    <div className={"pipeline-bar" + (dark ? " dark" : "")}>
      {/* Progress bar */}
      <div className="pipeline-progress">
        <div
          className="pipeline-fill"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>

      {/* Stage pills */}
      <div className="pipeline-stages">
        {stages.map((stage) => {
          const isDone = progress >= stage.progress_end;
          const isActive = !isDone && progress >= stage.progress_start;
          return (
            <div key={stage.name} className="ps">
              <span className={"ps-dot" + (isDone ? " done" : isActive ? " active" : "")} />
              <span className={"ps-label" + (isDone ? " done" : isActive ? " active" : "")}>
                {stage.label}
              </span>
            </div>
          );
        })}
        <span className="ps-status">{statusText}</span>
      </div>
    </div>
  );
}
