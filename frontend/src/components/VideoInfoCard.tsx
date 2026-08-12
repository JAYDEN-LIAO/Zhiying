/* ════════════════════════════════════════════════════════════
   VideoInfoCard — v2.0 minor-card grid layout
   Order: source analysis → AI detection → technical details → device → timestamps
   All sections use consistent .vif-item / .vif-lbl / .vif-val grid styling.
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { VideoMetadata, VideoResponse, SourceAnalysis, AIDetectResult } from "../types";
import { fmtDuration, fmtFullDate } from "../utils/helpers";

export function VideoInfoCard({
  videoId,
  video,
}: {
  videoId: string | null;
  video: VideoResponse | null;
}) {
  const [meta, setMeta] = useState<VideoMetadata | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoId) { setMeta(null); setError(null); return; }
    let cancelled = false;
    const fetchMeta = () => {
      setLoading(true);
      setError(null);
      api.fetchVideoMetadata(videoId)
        .then((d) => {
          if (cancelled) return;
          setMeta(d);
          setLoading(false);
          if (d?.ai_detect?.status === "analyzing") {
            setTimeout(fetchMeta, 3000);
          }
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err.message);
          setLoading(false);
        });
    };
    fetchMeta();
    return () => { cancelled = true; };
  }, [videoId]);

  const vs = meta?.video_streams?.[0];
  const a_s = meta?.audio_streams?.[0];
  const s_s = meta?.subtitle_streams;
  const dev = meta?.device;
  const ts = meta?.timestamps;
  const sa = meta?.source_analysis;
  const ad = meta?.ai_detect;

  /* ── Header portion ── */
  const hd = (
    <div className="minor-card-hd">
      <div className="minor-card-tt">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
        视频信息
      </div>
      {meta && <span className="minor-card-badge">{meta.container ?? ""}{meta.file_size != null ? ` · ${formatBytes(meta.file_size)}` : ""}</span>}
    </div>
  );

  /* ── No video ── */
  if (!video) {
    return <div className="minor-card">{hd}<div className="minor-card-bd flex items-center justify-center"><span className="text-gray-400 text-sm">选择视频后查看</span></div></div>;
  }

  /* ── Loading ── */
  if (loading) {
    return (
      <div className="minor-card">{hd}
        <div className="minor-card-bd">
          <div className="animate-pulse space-y-3 w-full">
            <div className="h-3 bg-gray-100 rounded w-2/3" />
            <div className="h-3 bg-gray-100 rounded w-full" />
            <div className="h-3 bg-gray-100 rounded w-3/4" />
            <div className="h-3 bg-gray-100 rounded w-1/2" />
          </div>
        </div>
      </div>
    );
  }

  /* ── Error ── */
  if (error) {
    return <div className="minor-card">{hd}<div className="minor-card-bd flex items-center justify-center"><span className="text-gray-400 text-sm">{error}</span></div></div>;
  }

  /* ── No metadata ── */
  if (!meta) {
    return <div className="minor-card">{hd}<div className="minor-card-bd flex items-center justify-center"><span className="text-gray-400 text-sm">暂无元数据</span></div></div>;
  }

  /* ── Has data ── */
  const hasSa = !!(sa && (sa.source_type || sa.source_label));
  const hasAd = !!(ad && ad.status === "completed");
  const showSeparator = hasSa || hasAd;

  return (
    <div className="minor-card">
      {hd}
      <div className="minor-card-bd space-y-2">

        {/* ═══ Source Analysis (top) ═══ */}
        {hasSa && (
          <div className="vif-grid">
            <SourceAnalysisItems sa={sa!} />
          </div>
        )}

        {/* ═══ AI Detection (top) ═══ */}
        {hasAd && (
          <div className="vif-grid">
            <AIDetectItems ad={ad!} />
          </div>
        )}

        {/* Separator before technical details */}
        {showSeparator && <div className="vif-div" />}

        {/* ═══ Technical details grid ═══ */}
        <div className="vif-grid">
          <div className="vif-item"><span className="vif-lbl">容器 / 封装</span><span className="vif-val">{meta.container ?? "—"}{meta.format_name && meta.format_name !== meta.container ? <span className="text-gray-400 text-[10px] ml-1">({meta.format_name})</span> : null}</span></div>
          <div className="vif-item"><span className="vif-lbl">时长</span><span className="vif-val">{meta.duration != null ? fmtDuration(meta.duration) : "—"}</span></div>
          {meta.overall_bitrate != null && (
            <div className="vif-item"><span className="vif-lbl">总码率</span><span className="vif-val"><span className="vif-hl">{`${(meta.overall_bitrate / 1_000_000).toFixed(1)} Mbps`}</span></span></div>
          )}

          {vs && <>
            <div className="vif-div" />
            <div className="vif-item"><span className="vif-lbl">视频编码</span><span className="vif-val"><code>{vs.codec ?? "—"}</code></span></div>
            <div className="vif-item"><span className="vif-lbl">分辨率</span><span className="vif-val">{vs.resolution ?? "—"}</span></div>
            <div className="vif-item"><span className="vif-lbl">帧率</span><span className="vif-val">{vs.fps != null ? `${vs.fps.toFixed(1)} fps` : "—"}</span></div>
            <div className="vif-item"><span className="vif-lbl">码率</span><span className="vif-val">{vs.bitrate != null ? <span className="vif-hl">{`${(vs.bitrate / 1_000_000).toFixed(1)} Mbps`}</span> : "—"}</span></div>
            {vs.codec_profile && <div className="vif-item"><span className="vif-lbl">编码档次</span><span className="vif-val">{vs.codec_profile}</span></div>}
            {vs.codec_level && <div className="vif-item"><span className="vif-lbl">编码级别</span><span className="vif-val">{vs.codec_level}</span></div>}
            {vs.pixel_format && <div className="vif-item"><span className="vif-lbl">像素格式</span><span className="vif-val">{vs.pixel_format}</span></div>}
            {vs.chroma_subsampling && <div className="vif-item"><span className="vif-lbl">色度采样</span><span className="vif-val">{vs.chroma_subsampling}</span></div>}
            {vs.bit_depth != null && <div className="vif-item"><span className="vif-lbl">位深</span><span className="vif-val">{`${vs.bit_depth}-bit`}</span></div>}
            {vs.color_space && <div className="vif-item"><span className="vif-lbl">色彩空间</span><span className="vif-val">{vs.color_space}</span></div>}
            {vs.color_primaries && <div className="vif-item"><span className="vif-lbl">色彩原色</span><span className="vif-val">{vs.color_primaries}</span></div>}
            {vs.transfer_characteristics && <div className="vif-item"><span className="vif-lbl">传递特性</span><span className="vif-val">{vs.transfer_characteristics}</span></div>}
            {vs.display_aspect_ratio && <div className="vif-item"><span className="vif-lbl">显示比例</span><span className="vif-val">{vs.display_aspect_ratio}</span></div>}
            {vs.rotation != null && vs.rotation !== 0 && <div className="vif-item"><span className="vif-lbl">旋转</span><span className="vif-val">{vs.rotation}°</span></div>}
            {vs.encoder && <div className="vif-item"><span className="vif-lbl">编码器</span><span className="vif-val">{vs.encoder}</span></div>}
          </>}

          {a_s && <>
            <div className="vif-div" />
            <div className="vif-item"><span className="vif-lbl">音频</span><span className="vif-val">{a_s.codec ?? "—"}{a_s.channels != null ? ` · ${formatChannels(a_s.channels, a_s.channel_layout ?? undefined)}` : ""}</span></div>
            <div className="vif-item"><span className="vif-lbl">采样率</span><span className="vif-val">{a_s.sample_rate != null ? `${(a_s.sample_rate / 1000).toFixed(0)} kHz` : "—"}</span></div>
            {a_s.bitrate != null && <div className="vif-item"><span className="vif-lbl">音频码率</span><span className="vif-val">{`${(a_s.bitrate / 1000).toFixed(0)} kbps`}</span></div>}
            {a_s.language && <div className="vif-item"><span className="vif-lbl">音频语言</span><span className="vif-val">{a_s.language}</span></div>}
          </>}

          {/* Subtitles */}
          {s_s?.map((sub, i) => (
            <div key={i} className="vif-item" style={i % 2 === 0 ? { gridColumn: "1 / -1" } : undefined}>
              <span className="vif-lbl">{`字幕 ${i + 1}`}</span>
              <span className="vif-val">{sub.format ?? "—"}{sub.language ? ` · ${sub.language}` : ""}{sub.forced ? " · 强制" : ""}{sub.title ? ` · ${sub.title}` : ""}</span>
            </div>
          ))}
        </div>

        {/* Device */}
        {dev && Object.keys(dev).length > 0 && (
          <div className="vif-grid">
            <div className="vif-div" />
            <div className="vif-item" style={{ gridColumn: "1 / -1" }}><span className="vif-lbl">设备信息</span><span className="vif-val">{dev.make ? `${dev.make}${dev.model ? ` ${dev.model}` : ""}` : dev.model ?? ""}</span></div>
            {dev.software && <div className="vif-item"><span className="vif-lbl">软件</span><span className="vif-val">{dev.software}</span></div>}
            {dev.gps_latitude != null && dev.gps_longitude != null && (
              <div className="vif-item" style={{ gridColumn: "1 / -1" }}><span className="vif-lbl">GPS</span><span className="vif-val font-mono">{dev.gps_latitude.toFixed(4)}, {dev.gps_longitude.toFixed(4)}{dev.gps_altitude != null ? ` (${dev.gps_altitude}m)` : ""}</span></div>
            )}
          </div>
        )}

        {/* Timestamps */}
        {ts && (ts.created || ts.modified) && (
          <div className="vif-grid">
            <div className="vif-div" />
            {ts.created && <div className="vif-item"><span className="vif-lbl">创建</span><span className="vif-val">{fmtISODate(ts.created)}</span></div>}
            {ts.modified && <div className="vif-item"><span className="vif-lbl">修改</span><span className="vif-val">{fmtISODate(ts.modified)}</span></div>}
          </div>
        )}

        {/* AI Detection — non-completed states at very bottom */}
        {ad && ad.status !== "completed" && <AIDetectFallback ad={ad} />}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   Source Analysis — vif-item rows
   ════════════════════════════════════════════════════════════ */

function SourceAnalysisItems({ sa }: { sa: SourceAnalysis }) {
  const survLabel = sa.surveillance_brand
    ? BRAND_LABELS[sa.surveillance_brand as keyof typeof BRAND_LABELS] ?? sa.surveillance_brand
    : null;

  return (
    <>
      <div className="vif-item">
        <span className="vif-lbl">来源分析</span>
        <span className="vif-val">{sa.source_label}{survLabel ? ` · ${survLabel}` : ""}</span>
      </div>
      {sa.surveillance_method && (
        <div className="vif-item">
          <span className="vif-lbl">识别方式</span>
          <span className="vif-val">
            {METHOD_LABELS[sa.surveillance_method] ?? sa.surveillance_method}
          </span>
        </div>
      )}
    </>
  );
}

/* ════════════════════════════════════════════════════════════
   AI Detection — vif-item rows (completed)
   ════════════════════════════════════════════════════════════ */

function AIDetectItems({ ad }: { ad: AIDetectResult }) {
  const isAi = ad.verdict === "ai_generated" || ad.verdict === "likely_ai";
  const verdictLabel = ad.verdict === "ai_generated" ? "AI 生成" : ad.verdict === "likely_ai" ? "疑似 AI" : ad.verdict === "no_signal" ? "无信号" : "—";
  const hasSignals = ad.signals.length > 0;

  return (
    <>
      <div className="vif-item">
        <span className="vif-lbl">
          AI 检测{ad.deep_analysis_used ? " [深度]" : ""}
        </span>
        <span className="vif-val">{isAi ? "⚠ " : "✓ "}{verdictLabel}</span>
      </div>
      {ad.score != null && (
        <div className="vif-item">
          <span className="vif-lbl">分数</span>
          <span className="vif-val">{ad.score >= 0.5 ? `${(ad.score * 100).toFixed(0)}%` : `${(ad.score * 100).toFixed(1)}%`}</span>
        </div>
      )}
      {hasSignals ? (
        ad.signals.map((s, i) => (
          <div key={i} className="vif-item">
            <span className="vif-lbl">{s.source}</span>
            <span className="vif-val">
              {s.tool && <span className="text-[10px]">{s.tool}</span>}
              {s.description && <span className="block text-[10px] text-gray-400">{s.description}</span>}
            </span>
          </div>
        ))
      ) : (
        <div className="vif-item">
          <span className="vif-lbl">检测项</span>
          <span className="vif-val text-[10px]">C2PA / H.264 SEI / MP4 元数据</span>
        </div>
      )}
      {ad.software_info.length > 0 && (
        <div className="vif-item">
          <span className="vif-lbl">检测工具</span>
          <span className="vif-val text-[10px]">{ad.software_info.map(s => s[0]).join(", ")}</span>
        </div>
      )}
    </>
  );
}

/* ════════════════════════════════════════════════════════════
   AI Detection — fallback for non-completed states
   ════════════════════════════════════════════════════════════ */

function AIDetectFallback({ ad }: { ad: AIDetectResult }) {
  if (ad.status === "not_run") {
    return <div className="text-[10px] text-gray-400 pt-1">AI 检测待分析</div>;
  }
  if (ad.status === "analyzing") {
    return <div className="text-[10px] text-amber-500 pt-1">AI 检测中…</div>;
  }
  if (ad.status === "error") {
    return <div className="text-[10px] text-red-500 pt-1">AI 检测失败{ad.error_message ? `: ${ad.error_message}` : ""}</div>;
  }
  return null;
}

const BRAND_LABELS: Record<string, string> = {
  hikvision: "海康威视", dahua: "大华", ezviz: "萤石", reolink: "Reolink",
  xiaomi: "小米", tplink: "TP-Link", uniview: "宇视", generic_ip: "通用网络摄像头", unknown: "未知",
};

const METHOD_LABELS: Record<string, string> = {
  magic_bytes: "文件头魔数", filename_pattern: "文件名模式", metadata: "元数据特征",
};

function formatBytes(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1000 * 1000) return `${(bytes / 1000).toFixed(1)} kB`;
  if (bytes < 1000 * 1000 * 1000) return `${(bytes / (1000 * 1000)).toFixed(1)} MB`;
  return `${(bytes / (1000 * 1000 * 1000)).toFixed(2)} GB`;
}

function formatChannels(n: number, layout?: string): string {
  if (layout) return layout;
  const map: Record<number, string> = { 1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1" };
  return map[n] ?? `${n} ch`;
}

function fmtISODate(iso: string): string {
  try {
    return fmtFullDate(iso);
  } catch { return iso; }
}
