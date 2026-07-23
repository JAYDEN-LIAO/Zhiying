/* ════════════════════════════════════════════════════════════
   VideoSummaryCard — extracted from Dashboard.tsx
   ════════════════════════════════════════════════════════════ */

import type { VideoResponse } from "../types";
import { formatSec } from "../utils/helpers";
import { api } from "../services/api";


export function VideoSummaryCard({ video }: { video: VideoResponse | null }) {
  const containerClass = "card-surface rounded-2xl p-4 border border-gray-200/60 min-h-[200px] flex flex-col h-full";

  if (!video) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频摘要</h3>
        <div className="flex-1 flex flex-col items-center justify-center gap-2">
          <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span className="text-gray-400 text-sm">选择视频后查看摘要</span>
        </div>
      </div>
    );
  }

  const summary = video.summary;

  // 摘要已生成 → 立即渲染（不管 status 是 processing 还是 completed）
  if (summary) {
    return (
      <div className={containerClass}>
        <div className="flex items-center justify-between mb-2 shrink-0">
          <h3 className="font-bold text-gray-900 text-lg">视频摘要</h3>
          <button
            onClick={() => { window.open(api.getThumbnailsExportUrl(video.id), "_blank"); }}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-blue-500 hover:bg-blue-50 transition-all shrink-0"
            title="导出全部缩略图"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
        </div>

        {/* One-liner */}
        <p className="text-gray-900 font-medium leading-relaxed mb-2 text-[13px] shrink-0">
          {summary.one_liner}
        </p>

        {/* Scenes */}
        {summary.scenes_summary.length > 0 && (
          <div className="flex-1 min-h-0 mb-2">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              场景片段
            </p>
            <div className="space-y-2 max-h-[200px] overflow-y-auto custom-scrollbar pr-1">
              {summary.scenes_summary.map((scene) => (
                <div key={scene.scene_index} className="flex items-start gap-2.5">
                  <img
                    src={`/api/v1/videos/${video.id}/thumbnail/${scene.scene_index}`}
                    alt=""
                    className="shrink-0 w-[60px] h-[45px] rounded-lg object-cover bg-gray-100 border border-gray-200"
                    loading="lazy"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                    }}
                  />
                  <div className="min-w-0 flex-1">
                    <span className="text-[11px] text-gray-400 font-mono">
                      {formatSec(scene.start_sec)} — {formatSec(scene.end_sec)}
                    </span>
                    <p className="text-xs text-gray-700 leading-relaxed">
                      {scene.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Topics + Tags */}
        <div className="shrink-0 pt-2 border-t border-gray-100 space-y-1">
          {summary.main_topics.length > 0 && (
            <div className="text-[11px] text-gray-500">
              {summary.main_topics.map((t, i) => (
                <span key={t}>
                  {i > 0 && <span className="mx-1.5 text-gray-300">·</span>}
                  {t}
                </span>
              ))}
            </div>
          )}
          {summary.tags.length > 0 && (
            <div className="text-[11px] text-gray-400">
              {summary.tags.map((tag, i) => (
                <span key={tag}>
                  {i > 0 && <span className="mx-1.5 text-gray-300">·</span>}
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // 处理中但摘要还没生成 → 骨架屏
  if (video.status === "processing" || video.status === "pending") {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频摘要</h3>
        <div className="flex-1 flex items-center">
          <div className="animate-pulse space-y-3 w-full">
            <div className="h-4 bg-gray-100 rounded w-3/4" />
            <div className="h-3 bg-gray-100 rounded w-full" />
            <div className="h-3 bg-gray-100 rounded w-5/6" />
            <div className="flex gap-2">
              <div className="h-5 bg-gray-100 rounded-full w-14" />
              <div className="h-5 bg-gray-100 rounded-full w-18" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 处理完成但摘要未开启
  if (video.status === "completed" && !video.summary_enabled) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频摘要</h3>
        <div className="flex-1 flex flex-col items-center justify-center gap-1 opacity-50">
          <span className="text-gray-400 text-sm">摘要功能未开启</span>
          <span className="text-xs text-gray-300">请在参数设置中启用「智能摘要」</span>
        </div>
      </div>
    );
  }

  // 已完成但无摘要数据（异常兜底）
  return (
    <div className={containerClass}>
      <h3 className="font-bold text-gray-900 text-lg mb-2">视频摘要</h3>
      <div className="flex-1 flex items-center justify-center">
        <span className="text-gray-400 text-sm">暂无摘要数据</span>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   VideoSearchCard — 连接后端 API
   ════════════════════════════════════════════════════════════ */

