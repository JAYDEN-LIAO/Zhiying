import { IconText } from "../icons";
import type { VideoResponse } from "../../types";

/* ════════════════════════════════════════════════════════════
   SummaryPanel — 视频摘要（右侧区域顶部通栏，约 22% 高）
   已开启摘要 → 展示一句话摘要 + 标签
   未开启 → 居中灰字占位「摘要功能未开启」
   ════════════════════════════════════════════════════════════ */

export function SummaryPanel({ video }: { video: VideoResponse | null }) {
  const summary = video?.summary;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-card bg-card-bg shadow-card">
      {/* 标题栏 */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border-light px-4 py-2.5">
        <span className="text-primary"><IconText /></span>
        <p className="text-sm font-semibold text-gray-700">视频摘要</p>
      </div>

      {/* 内容区 */}
      {summary ? (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-4">
          <p className="text-sm leading-relaxed text-gray-600">{summary.one_liner}</p>
          {summary.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {summary.tags.map((t) => (
                <span key={t} className="rounded-full bg-primary-soft px-2 py-0.5 text-xs text-primary">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <p className="text-sm text-gray-400">摘要功能未开启</p>
        </div>
      )}
    </div>
  );
}
