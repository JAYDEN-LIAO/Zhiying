/* ════════════════════════════════════════════════════════════
   VideoInfoCard — 视频元数据信息卡片（右侧栏顶部）
   样式对齐 VideoSummaryCard / VideoSearchCard
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { VideoMetadata, VideoResponse } from "../types";
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
    setLoading(true);
    setError(null);
    api.fetchVideoMetadata(videoId)
      .then((d) => { setMeta(d); setLoading(false); })
      .catch((err) => { setError(err.message); setLoading(false); });
  }, [videoId]);

  const containerClass = "card-surface rounded-2xl p-3 border border-gray-200/60 flex flex-col h-full";

  const vs = meta?.video_streams?.[0];
  const a_s = meta?.audio_streams?.[0];
  const dev = meta?.device;
  const ts = meta?.timestamps;

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
      </div>
    </div>
  );
}

/* ── Sub-components ── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{title}</h4>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-gray-500 shrink-0 mr-3">{label}</span>
      <span className="text-gray-800 text-right font-mono break-all max-w-[60%]">{value}</span>
    </div>
  );
}

/* ── Helpers ── */

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
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
