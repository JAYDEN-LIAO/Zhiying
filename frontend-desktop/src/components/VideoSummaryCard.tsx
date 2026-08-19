/* ════════════════════════════════════════════════════════════
   VideoSummaryCard — v0.34 摘要卡片 + 浏览器式标签页（摘要 | 文字）
   ════════════════════════════════════════════════════════════ */

import { useEffect, useState } from "react";
import type { VideoResponse, OcrData } from "../types";
import { formatSec } from "../utils/helpers";
import { api } from "../services/api";

export function VideoSummaryCard({ video, onSeekTo }: {
  video: VideoResponse | null;
  onSeekTo?: (sec: number) => void;
}) {
  const [tab, setTab] = useState<"summary" | "ocr">("summary");

  // 切换视频/版本 → 回到摘要 tab
  useEffect(() => { setTab("summary"); }, [video?.id]);

  /* ── No video ── */
  if (!video) {
    return (
      <div className="minor-card">
        <div className="minor-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">选择视频后查看摘要 / 文字</span>
        </div>
      </div>
    );
  }

  return (
    <div className="minor-card">
      <div className="ocr-tabbar">
        <button
          className={tab === "summary" ? "ocr-tab active" : "ocr-tab"}
          onClick={() => setTab("summary")}
        >摘要</button>
        <button
          className={tab === "ocr" ? "ocr-tab active" : "ocr-tab"}
          onClick={() => setTab("ocr")}
        >文字</button>
      </div>
      <div className="minor-card-bd">
        {tab === "summary"
          ? <SummaryBody video={video} />
          : <OcrBody video={video} onSeekTo={onSeekTo} />}
      </div>
    </div>
  );
}

/* ── 摘要 tab：原摘要内容（one_liner + 场景列表 + 空态） ── */
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

  /* ── Summary not enabled（OCR 独立模式常见：仅文字，无摘要） ── */
  if (video.status === "completed" && !video.summary_enabled) {
    return (
      <div className="flex items-center justify-center py-6 opacity-50">
        <div className="text-center">
          <p className="text-gray-400 text-sm">摘要功能未开启</p>
          <p className="text-xs text-gray-300">本视频以文字提取为主，可切到「文字」标签页查看结果</p>
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

/* ── 文字 tab：按时间戳的 OCR 文字清单，点击整行跳转定位 ── */
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