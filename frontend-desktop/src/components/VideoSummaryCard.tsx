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


        <div className="minor-card-bd">
          {/* One-liner（Tags 已上移卡片标题栏右侧） */}
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
        </div>
      </div>
    );
  }

  /* ── Processing（统一空态：居中灰字，与检测/搜索卡一致） ── */
  if (video.status === "processing" || video.status === "pending") {
    return (
      <div className="minor-card">
        <div className="minor-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">视频处理完成后自动生成摘要</span>
        </div>
      </div>
    );
  }

  /* ── Summary not enabled ── */
  if (video.status === "completed" && !video.summary_enabled) {
    return (
      <div className="minor-card">

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
      <div className="minor-card-bd flex items-center justify-center">
        <span className="text-gray-400 text-sm">暂无摘要数据</span>
      </div>
    </div>
  );
}
