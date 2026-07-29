/* ════════════════════════════════════════════════════════════
   VideoSummaryCard — v2.0 minor-card style
   ════════════════════════════════════════════════════════════ */

import type { VideoResponse } from "../types";
import { formatSec } from "../utils/helpers";
import { api } from "../services/api";

export function VideoSummaryCard({ video }: { video: VideoResponse | null }) {
  /* ── No video ── */
  if (!video) {
    return (
      <div className="minor-card">
        <div className="minor-card-hd">
          <div className="minor-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            视频摘要
          </div>
        </div>
        <div className="minor-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">选择视频后查看摘要</span>
        </div>
      </div>
    );
  }

  const summary = video.summary;

  /* ── Summary data available ── */
  if (summary) {
    return (
      <div className="minor-card">
        <div className="minor-card-hd">
          <div className="minor-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            视频摘要
          </div>
          <button
            onClick={() => { window.open(api.getThumbnailsExportUrl(video.id), "_blank"); }}
            className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-300 hover:text-blue-500 hover:bg-blue-50 transition-all shrink-0 cursor-pointer"
            title="导出全部缩略图"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
        </div>

        <div className="minor-card-bd">
          {/* One-liner */}
          <div className="sum-one">{summary.one_liner}</div>

          {/* Scenes */}
          {summary.scenes_summary.length > 0 && (
            <div className="sum-scenes">
              {summary.scenes_summary.map((scene) => (
                <div key={scene.scene_index} className="sum-scene">
                  <div className="sum-thumb">
                    <img
                      src={`/api/v1/videos/${video.id}/thumbnail/${scene.scene_index}`}
                      alt=""
                      loading="lazy"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                  </div>
                  <div className="sum-si">
                    <div className="sum-tm">{formatSec(scene.start_sec)} — {formatSec(scene.end_sec)}</div>
                    <div className="sum-desc">{scene.description}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Tags */}
          {summary.tags.length > 0 && (
            <div className="sum-tags">
              {summary.tags.map((tag) => (
                <span key={tag} className="sum-tag">{tag}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ── Processing skeleton ── */
  if (video.status === "processing" || video.status === "pending") {
    return (
      <div className="minor-card">
        <div className="minor-card-hd">
          <div className="minor-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            视频摘要
          </div>
        </div>
        <div className="minor-card-bd">
          <div className="animate-pulse space-y-3 w-full">
            <div className="h-4 bg-gray-100 rounded w-3/4" />
            <div className="h-3 bg-gray-100 rounded w-full" />
            <div className="h-3 bg-gray-100 rounded w-5/6" />
            <div className="flex gap-2">
              <div className="h-5 bg-gray-100 rounded-full w-14" />
              <div className="h-5 bg-gray-100 rounded-full w-16" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ── Summary not enabled ── */
  if (video.status === "completed" && !video.summary_enabled) {
    return (
      <div className="minor-card">
        <div className="minor-card-hd">
          <div className="minor-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            视频摘要
          </div>
        </div>
        <div className="minor-card-bd flex items-center justify-center opacity-50">
          <div className="text-center">
            <p className="text-gray-400 text-sm">摘要功能未开启</p>
            <p className="text-xs text-gray-300">请在参数设置中启用「智能摘要」</p>
          </div>
        </div>
      </div>
    );
  }

  /* ── Fallback ── */
  return (
    <div className="minor-card">
      <div className="minor-card-hd">
        <div className="minor-card-tt">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          视频摘要
        </div>
      </div>
      <div className="minor-card-bd flex items-center justify-center">
        <span className="text-gray-400 text-sm">暂无摘要数据</span>
      </div>
    </div>
  );
}
