/* ════════════════════════════════════════════════════════════
   VideoInfoCard — 视频元数据信息卡片（右侧栏顶部）
   样式对齐 VideoSummaryCard / VideoSearchCard
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
          // AI 检测中 → 3s 后自动刷新
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

  const containerClass = "card-surface rounded-2xl p-3 border border-gray-200/60 flex flex-col h-full";

  const vs = meta?.video_streams?.[0];
  const a_s = meta?.audio_streams?.[0];
  const dev = meta?.device;
  const ts = meta?.timestamps;
  const sa = meta?.source_analysis;
  const ad = meta?.ai_detect;

  /* ── 1. No video selected ── */
  if (!video) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频信息</h3>
        <div className="flex-1 flex flex-col items-center justify-center gap-2">
          <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          <span className="text-gray-400 text-sm">选择视频后查看</span>
        </div>
      </div>
    );
  }

  /* ── 2. Loading ── */
  if (loading) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频信息</h3>
        <div className="flex-1 flex items-center">
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

  /* ── 3. Error ── */
  if (error) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频信息</h3>
        <div className="flex-1 flex items-center justify-center">
          <span className="text-gray-400 text-sm">{error}</span>
        </div>
      </div>
    );
  }

  /* ── 4. No metadata ── */
  if (!meta) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频信息</h3>
        <div className="flex-1 flex items-center justify-center">
          <span className="text-gray-400 text-sm">暂无元数据</span>
        </div>
      </div>
    );
  }

  /* ── 5. Has metadata ── */
  return (
    <div className={containerClass}>
      <h3 className="font-bold text-gray-900 text-lg mb-2 shrink-0">视频信息</h3>
      <div className="flex-1 overflow-y-auto custom-scrollbar pr-0.5 space-y-3 text-[11px]">
        {/* File Format */}
        <Section title="文件格式">
          <Row label="容器" value={meta.container ?? "—"} />
          <Row label="时长" value={meta.duration != null ? fmtDuration(meta.duration) : "—"} />
          <Row label="大小" value={meta.file_size != null ? formatBytes(meta.file_size) : "—"} />
          {meta.overall_bitrate != null && (
            <Row label="总码率" value={`${(meta.overall_bitrate / 1000).toFixed(0)} kbps`} />
          )}
        </Section>

        {/* Video Stream */}
        {vs && (
          <Section title="视频流">
            <Row label="编码" value={vs.codec ?? "—"} />
            {vs.codec_profile && <Row label="配置" value={vs.codec_profile} />}
            <Row label="分辨率" value={vs.resolution ?? "—"} />
            {vs.display_aspect_ratio && <Row label="宽高比" value={vs.display_aspect_ratio} />}
            {vs.fps != null && <Row label="帧率" value={`${vs.fps.toFixed(1)} fps`} />}
            {vs.bitrate != null && <Row label="码率" value={`${(vs.bitrate / 1000).toFixed(0)} kbps`} />}
            {vs.pixel_format && <Row label="像素格式" value={vs.pixel_format} />}
            {vs.color_space && <Row label="色彩空间" value={vs.color_space} />}
            {vs.bit_depth != null && <Row label="位深" value={`${vs.bit_depth}-bit`} />}
            {vs.rotation != null && vs.rotation !== 0 && <Row label="旋转" value={`${vs.rotation}°`} />}
          </Section>
        )}

        {/* Audio Stream */}
        {a_s && (
          <Section title="音频流">
            <Row label="编码" value={a_s.codec ?? "—"} />
            {a_s.channels != null && <Row label="声道" value={formatChannels(a_s.channels, a_s.channel_layout ?? undefined)} />}
            {a_s.sample_rate != null && <Row label="采样率" value={`${(a_s.sample_rate / 1000).toFixed(0)} kHz`} />}
            {a_s.bitrate != null && <Row label="码率" value={`${(a_s.bitrate / 1000).toFixed(0)} kbps`} />}
            {a_s.language && <Row label="语言" value={a_s.language} />}
          </Section>
        )}

        {/* Device Info */}
        {dev && Object.keys(dev).length > 0 && (
          <Section title="设备信息">
            {dev.make && dev.model && (
              <Row label="设备" value={`${dev.make} ${dev.model}`} />
            )}
            {!dev.make && dev.model !== undefined && <Row label="设备" value={dev.model} />}
            {dev.software && <Row label="软件" value={dev.software} />}
            {dev.gps_latitude != null && dev.gps_longitude != null && (
              <Row label="GPS" value={`${dev.gps_latitude.toFixed(4)}, ${dev.gps_longitude.toFixed(4)}${dev.gps_altitude != null ? ` (${dev.gps_altitude}m)` : ""}`} />
            )}
          </Section>
        )}

        {/* Timestamps */}
        {ts && (ts.created || ts.modified) && (
          <Section title="时间">
            {ts.created && <Row label="创建" value={fmtISODate(ts.created)} />}
            {ts.modified && <Row label="修改" value={fmtISODate(ts.modified)} />}
          </Section>
        )}

        {/* Source Analysis (v0.17) */}
        {sa && <SourceAnalysisSection sa={sa} />}

        {/* AI Detection (v0.17) */}
        {ad && <AIDetectSection ad={ad} />}
      </div>
    </div>
  );
}

/* ── Source Analysis section (v0.17) ── */

function SourceAnalysisSection({ sa }: { sa: SourceAnalysis }) {
  const confColor = sa.confidence === "high" ? "text-green-600" : sa.confidence === "medium" ? "text-amber-500" : "text-gray-400";
  const confIcon = sa.confidence === "high" ? "✓" : sa.confidence === "medium" ? "~" : "?";
  const survLabel = sa.surveillance_brand
    ? BRAND_LABELS[sa.surveillance_brand as keyof typeof BRAND_LABELS] ?? sa.surveillance_brand
    : null;

  return (
    <Section title="来源分析">
      <Row label="来源类型" value={sa.source_label} />
      <Row label="置信度" value={
        <span className={confColor}>{confIcon} {sa.confidence === "high" ? "高置信度" : sa.confidence === "medium" ? "中置信度" : "低置信度"}</span>
      } />
      {sa.evidence.length > 0 && (
        <div className="text-gray-400 text-[10px] mt-0.5 space-y-0.5">
          {sa.evidence.map((e, i) => <div key={i} className="pl-2 border-l-2 border-gray-200">{e}</div>)}
        </div>
      )}
      {survLabel && <Row label="监控品牌" value={survLabel} />}
    </Section>
  );
}

/* ── AI Detection section (v0.17) ── */

function AIDetectSection({ ad }: { ad: AIDetectResult }) {
  if (ad.status === "not_run") {
    return <Section title="AI 生成检测"><Row label="状态" value="待分析" /></Section>;
  }

  if (ad.status === "analyzing") {
    return (
      <Section title="AI 生成检测">
        <Row label="状态" value={<span className="text-amber-500">检测中...</span>} />
        <div className="text-[10px] text-gray-400 mt-0.5 pl-2 border-l-2 border-gray-200">
          正在扫描 C2PA 签名 / H.264 SEI 水印 / 像素级水印分析
        </div>
      </Section>
    );
  }

  if (ad.status === "error") {
    return (
      <Section title="AI 生成检测">
        <Row label="状态" value={<span className="text-red-500">检测失败</span>} />
        {ad.error_message && <Row label="错误" value={ad.error_message} />}
      </Section>
    );
  }

  const isAi = ad.verdict === "ai_generated" || ad.verdict === "likely_ai";
  const verdictLabel = ad.verdict === "ai_generated" ? "AI 生成"
    : ad.verdict === "likely_ai" ? "疑似 AI 生成"
    : ad.verdict === "no_signal" ? "未检测到 AI 信号" : "—";
  const verdictColor = isAi ? "text-red-600" : "text-green-600";
  const verdictIcon = isAi ? "⚠" : "✓";

  const highSignals = ad.signals.filter(s => s.confidence === "high");
  const medSignals = ad.signals.filter(s => s.confidence === "medium");

  return (
    <Section title={`AI 生成检测${ad.deep_analysis_used ? " [深度检测]" : ""}`}>
      <Row label="结果" value={<span className={verdictColor}>{verdictIcon} {verdictLabel}</span>} />
      {ad.score != null && (
        <Row label="综合分数" value={ad.score >= 0.5 ? `${(ad.score * 100).toFixed(0)}%` : `${(ad.score * 100).toFixed(1)}%`} />
      )}
      {highSignals.length > 0 && (
        <div className="mt-1 space-y-0.5">
          <h5 className="text-[9px] font-medium text-red-500 uppercase tracking-wide">HIGH 信号</h5>
          {highSignals.map((s, i) => <SignalRow key={i} signal={s} />)}
        </div>
      )}
      {medSignals.length > 0 && (
        <div className="mt-1 space-y-0.5">
          <h5 className="text-[9px] font-medium text-amber-500 uppercase tracking-wide">MEDIUM 信号</h5>
          {medSignals.map((s, i) => <SignalRow key={i} signal={s} />)}
        </div>
      )}
      {ad.verdict === "no_signal" && ad.signals.length === 0 && (
        <div className="text-[10px] text-gray-400 mt-0.5 pl-2 border-l-2 border-gray-200">
          已检查 C2PA 签名 / H.264 SEI 水印 / MP4 元数据 / 文件名 / AIGC 标签
        </div>
      )}
      {ad.deep_analysis_used && <Row label="深度分析" value="已执行像素级水印检测" />}
    </Section>
  );
}

function SignalRow({ signal }: { signal: { source: string; description: string; tool: string | null } }) {
  return (
    <div className="text-[10px] pl-2 border-l-2 border-gray-200">
      <span className="font-medium text-gray-600">{signal.source}</span>
      {signal.tool && <span className="text-gray-400 ml-1">→ {signal.tool}</span>}
      <div className="text-gray-400 truncate">{signal.description}</div>
    </div>
  );
}

const BRAND_LABELS: Record<string, string> = {
  hikvision: "海康威视",
  dahua: "大华",
  ezviz: "萤石",
  reolink: "Reolink",
  xiaomi: "小米",
  tplink: "TP-Link",
  uniview: "宇视",
  generic_ip: "通用网络摄像头",
  unknown: "未知",
};

/* ── Sub-components ── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{title}</h4>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-gray-500 shrink-0 mr-3">{label}</span>
      {typeof value === "string" ? (
        <span className="text-gray-800 text-right font-mono break-all max-w-[60%]">{value}</span>
      ) : (
        <span className="text-gray-800 text-right max-w-[60%]">{value}</span>
      )}
    </div>
  );
}

/* ── Helpers ── */

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
  } catch {
    return iso;
  }
}
