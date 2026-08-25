/* ════════════════════════════════════════════════════════════
   VideoSummaryCard — 摘要 / 文字识别内容渲染（v0.6：tab 由外部控制）
   ════════════════════════════════════════════════════════════ */

import { useEffect, useState } from "react";
import type { VideoResponse, OcrData } from "../types";
import { formatSec } from "../utils/helpers";
import { api } from "../services/api";

export function VideoSummaryCard({ video, onSeekTo, tab }: {
  video: VideoResponse | null;
  onSeekTo?: (sec: number) => void;
  tab?: "summary" | "ocr";
}) {
  /* ── No video ── */
  if (!video) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-gray-400 text-sm">选择视频后查看摘要 / 文字</span>
      </div>
    );
  }

  return (
    <>
      {tab === "ocr"
        ? <OcrBody video={video} onSeekTo={onSeekTo} />
        : <SummaryBody video={video} />}
    </>
  );
}

/* ── 摘要内容（one_liner + 场景列表 + 空态） ── */
function SummaryBody({ video }: { video: VideoResponse }) {
  const summary = video.summary;

  if (summary) {
    return (
      <>
        <div className="sum-one">{summary.one_liner}</div>
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
      </>
    );
  }

  /* ── Processing ── */
  if (video.status === "processing" || video.status === "pending") {
    return (
      <div className="flex items-center justify-center py-6">
        <span className="text-gray-400 text-sm">视频处理完成后自动生成摘要</span>
      </div>
    );
  }

  /* ── Summary not enabled ── */
  if (video.status === "completed" && !video.summary_enabled) {
    return (
      <div className="flex items-center justify-center py-6 opacity-50">
        <div className="text-center">
          <p className="text-gray-400 text-sm">摘要功能未开启</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center py-6">
      <span className="text-gray-400 text-sm">暂无摘要数据</span>
    </div>
  );
}

/* ── 文字识别内容：按时间戳的 OCR 文字清单，点击跳转定位 ── */
function OcrBody({ video, onSeekTo }: { video: VideoResponse; onSeekTo?: (sec: number) => void }) {
  const [data, setData] = useState<OcrData | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setState("loading");
    setErr("");
    setData(null);
    api.fetchOcrData(video.id)
      .then((d) => { if (alive) { setData(d); setState("ready"); } })
      .catch((e) => {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      });
    return () => { alive = false; };
  }, [video.id]);

  if (state === "loading") {
    return (
      <div className="flex items-center justify-center py-6">
        <span className="text-gray-400 text-sm">文字提取加载中…</span>
      </div>
    );
  }
  if (state === "error") {
    return (
      <div className="flex items-center justify-center py-6">
        <span className="text-red-500 text-sm">文字数据加载失败：{err}</span>
      </div>
    );
  }

  const dets = data?.detections ?? [];
  if (dets.length === 0) {
    return (
      <div className="flex items-center justify-center py-6">
        <span className="text-gray-400 text-sm">未提取到文字（可在参数面板开启「文字识别」重新解析）</span>
      </div>
    );
  }

  return (
    <div className="sum-scenes">
      {dets.map((d) => (
        <button
          key={d.id}
          className="ocr-row"
          onClick={() => onSeekTo?.(d.timestamp_sec)}
          title={`跳转到 ${formatSec(d.timestamp_sec)}`}
        >
          <span className="ocr-tm">{formatSec(d.timestamp_sec)}</span>
          <span className="ocr-text">{d.text}</span>
        </button>
      ))}
    </div>
  );
}
