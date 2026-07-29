/* ════════════════════════════════════════════════════════════
   VideoInfoCard — v2.0 minor-card grid layout
   Preserves: source analysis, AI detection, device info, timestamps
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { VideoMetadata, VideoResponse, SourceAnalysis, AIDetectResult } from "../types";
import { fmtDuration } from "../utils/helpers";

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
  return (
    <div className="minor-card">
      {hd}
      <div className="minor-card-bd space-y-2">
        <div className="vif-grid">
          <div className="vif-item"><span className="vif-lbl">容器</span><span className="vif-val"><code>{meta.container ?? "—"}</code></span></div>
          <div className="vif-item"><span className="vif-lbl">时长</span><span className="vif-val">{meta.duration != null ? fmtDuration(meta.duration) : "—"}</span></div>
          {vs && <>
            <div className="vif-item"><span className="vif-lbl">编码</span><span className="vif-val"><code>{vs.codec ?? "—"}</code></span></div>
            <div className="vif-item"><span className="vif-lbl">分辨率</span><span className="vif-val">{vs.resolution ?? "—"}</span></div>
            <div className="vif-div" />
            <div className="vif-item"><span className="vif-lbl">帧率</span><span className="vif-val">{vs.fps != null ? `${vs.fps.toFixed(1)} fps` : "—"}</span></div>
            <div className="vif-item"><span className="vif-lbl">码率</span><span className="vif-val">{vs.bitrate != null ? <span className="vif-hl">{`${(vs.bitrate / 1000).toFixed(1)} Mbps`}</span> : "—"}</span></div>
            {vs.pixel_format && <div className="vif-item"><span className="vif-lbl">像素格式</span><span className="vif-val">{vs.pixel_format}</span></div>}
            {vs.bit_depth != null && <div className="vif-item"><span className="vif-lbl">位深</span><span className="vif-val">{`${vs.bit_depth}-bit`}</span></div>}
            {a_s && <div className="vif-div" />}
          </>}
          {a_s && <>
            <div className="vif-item"><span className="vif-lbl">音频</span><span className="vif-val">{a_s.codec ?? "—"}{a_s.channels != null ? ` · ${formatChannels(a_s.channels, a_s.channel_layout ?? undefined)}` : ""}</span></div>
            <div className="vif-item"><span className="vif-lbl">采样率</span><span className="vif-val">{a_s.sample_rate != null ? `${(a_s.sample_rate / 1000).toFixed(0)} kHz` : "—"}</span></div>
          </>}
        </div>

        {/* Device */}
        {dev && Object.keys(dev).length > 0 && (
          <div className="pt-2 border-t border-gray-100">
            <div className="text-[9px] font-semibold text-gray-500 uppercase tracking-wide mb-1">设备信息</div>
            <div className="space-y-0.5 text-[10px]">
              {dev.make && dev.model && <div className="flex justify-between"><span className="text-gray-500">{dev.make}</span><span className="text-gray-800 font-mono">{dev.model}</span></div>}
              {!dev.make && dev.model != null && <div className="flex justify-between"><span className="text-gray-500">设备</span><span className="text-gray-800 font-mono">{dev.model}</span></div>}
              {dev.software && <div className="flex justify-between"><span className="text-gray-500">软件</span><span className="text-gray-800 font-mono">{dev.software}</span></div>}
              {dev.gps_latitude != null && dev.gps_longitude != null && (
                <div className="flex justify-between"><span className="text-gray-500">GPS</span><span className="text-gray-800 font-mono">{dev.gps_latitude.toFixed(4)}, {dev.gps_longitude.toFixed(4)}{dev.gps_altitude != null ? ` (${dev.gps_altitude}m)` : ""}</span></div>
              )}
            </div>
          </div>
        )}

        {/* Timestamps */}
        {ts && (ts.created || ts.modified) && (
          <div className="pt-2 border-t border-gray-100 space-y-0.5 text-[10px]">
            {ts.created && <div className="flex justify-between"><span className="text-gray-500">创建</span><span className="text-gray-800 font-mono">{fmtISODate(ts.created)}</span></div>}
            {ts.modified && <div className="flex justify-between"><span className="text-gray-500">修改</span><span className="text-gray-800 font-mono">{fmtISODate(ts.modified)}</span></div>}
          </div>
        )}

        {/* Source Analysis */}
        {sa && <SourceAnalysisSection sa={sa} />}

        {/* AI Detection */}
        {ad && <AIDetectSection ad={ad} />}
      </div>
    </div>
  );
}

/* ── Sub-sections ── */

function SourceAnalysisSection({ sa }: { sa: SourceAnalysis }) {
  const confColor = sa.confidence === "high" ? "text-green-600" : sa.confidence === "medium" ? "text-amber-500" : "text-gray-400";
  const confIcon = sa.confidence === "high" ? "✓" : sa.confidence === "medium" ? "~" : "?";
  const survLabel = sa.surveillance_brand ? BRAND_LABELS[sa.surveillance_brand as keyof typeof BRAND_LABELS] ?? sa.surveillance_brand : null;
  return (
    <div className="pt-2 border-t border-gray-100">
      <div className="text-[9px] font-semibold text-gray-500 uppercase tracking-wide mb-1">来源分析</div>
      <div className="space-y-0.5 text-[10px]">
        <div className="flex justify-between"><span className="text-gray-500">类型</span><span className="text-gray-800">{sa.source_label}</span></div>
        <div className="flex justify-between"><span className="text-gray-500">置信度</span><span className={confColor}>{confIcon} {sa.confidence === "high" ? "高" : sa.confidence === "medium" ? "中" : "低"}</span></div>
        {sa.evidence.length > 0 && <div className="text-gray-400 text-[10px] space-y-0.5">{sa.evidence.map((e, i) => <div key={i} className="pl-2 border-l-2 border-gray-200">{e}</div>)}</div>}
        {survLabel && <div className="flex justify-between"><span className="text-gray-500">品牌</span><span className="text-gray-800">{survLabel}</span></div>}
      </div>
    </div>
  );
}

function AIDetectSection({ ad }: { ad: AIDetectResult }) {
  if (ad.status === "not_run") {
    return <div className="pt-2 border-t border-gray-100"><div className="text-[9px] font-semibold text-gray-500 uppercase tracking-wide mb-1">AI 检测</div><div className="text-[10px] text-gray-500">待分析</div></div>;
  }
  if (ad.status === "analyzing") {
    return <div className="pt-2 border-t border-gray-100"><div className="text-[9px] font-semibold text-gray-500 uppercase tracking-wide mb-1">AI 检测</div><div className="text-[10px] text-amber-500">检测中...</div><div className="text-[10px] text-gray-400 pl-2 border-l-2 border-gray-200">扫描 C2PA / H.264 SEI / 像素水印</div></div>;
  }
  if (ad.status === "error") {
    return <div className="pt-2 border-t border-gray-100"><div className="text-[9px] font-semibold text-gray-500 uppercase tracking-wide mb-1">AI 检测</div><div className="text-[10px] text-red-500">检测失败</div>{ad.error_message && <div className="text-[10px] text-gray-400">{ad.error_message}</div>}</div>;
  }
  const isAi = ad.verdict === "ai_generated" || ad.verdict === "likely_ai";
  const verdictLabel = ad.verdict === "ai_generated" ? "AI 生成" : ad.verdict === "likely_ai" ? "疑似 AI" : ad.verdict === "no_signal" ? "无信号" : "—";
  const verdictColor = isAi ? "text-red-600" : "text-green-600";
  return (
    <div className="pt-2 border-t border-gray-100">
      <div className="text-[9px] font-semibold text-gray-500 uppercase tracking-wide mb-1">AI 检测{ad.deep_analysis_used ? " [深度]" : ""}</div>
      <div className="space-y-0.5 text-[10px]">
        <div className="flex justify-between"><span className="text-gray-500">结果</span><span className={verdictColor}>{isAi ? "⚠" : "✓"} {verdictLabel}</span></div>
        {ad.score != null && <div className="flex justify-between"><span className="text-gray-500">分数</span><span>{ad.score >= 0.5 ? `${(ad.score * 100).toFixed(0)}%` : `${(ad.score * 100).toFixed(1)}%`}</span></div>}
        {ad.signals.filter(s => s.confidence === "high").map((s, i) => <div key={i} className="text-red-500 pl-2 border-l-2 border-red-200"><span className="font-medium">{s.source}</span>{s.tool ? ` → ${s.tool}` : ""}<div className="text-gray-400 truncate">{s.description}</div></div>)}
        {ad.signals.filter(s => s.confidence === "medium").map((s, i) => <div key={i} className="text-amber-500 pl-2 border-l-2 border-amber-200"><span className="font-medium">{s.source}</span>{s.tool ? ` → ${s.tool}` : ""}<div className="text-gray-400 truncate">{s.description}</div></div>)}
        {ad.verdict === "no_signal" && ad.signals.length === 0 && <div className="text-[10px] text-gray-400 pl-2 border-l-2 border-gray-200">已检查 C2PA / H.264 SEI / MP4 元数据</div>}
        {ad.deep_analysis_used && <div className="text-[10px] text-gray-400">已执行像素级水印分析</div>}
      </div>
    </div>
  );
}

const BRAND_LABELS: Record<string, string> = {
  hikvision: "海康威视", dahua: "大华", ezviz: "萤石", reolink: "Reolink",
  xiaomi: "小米", tplink: "TP-Link", uniview: "宇视", generic_ip: "通用网络摄像头", unknown: "未知",
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
    const d = new Date(iso);
    return d.toLocaleString(undefined, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}
