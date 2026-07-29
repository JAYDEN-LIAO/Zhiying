/* ════════════════════════════════════════════════════════════
   PipelineBar — v2.0 new style (mockup-dark)
   ════════════════════════════════════════════════════════════ */

import { useMemo } from "react";
import { computePipelineStages } from "../mockData";
import type { PipelineSwitches } from "../mockData";

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

  const statusText = subtitle
    || (isEmpty ? "选择视频后查看处理进度" : isComplete ? "处理完成 ✓" : (statusDetail || "处理中..."));

  return (
    <div className="pipeline-bar">
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
          const isDone = progress >= stage.progressEnd;
          const isActive = !isDone && progress >= stage.progressStart;
          return (
            <div key={stage.id} className="ps">
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
