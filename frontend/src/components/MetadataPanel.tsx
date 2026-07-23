/* ════════════════════════════════════════════════════════════
   MetadataPanel — 视频元数据信息卡片
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { VideoMetadata } from "../types";
import { fmtDuration } from "../utils/helpers";
import { IconClose } from "./icons";

export function MetadataPanel({
  videoId,
  onClose,
}: {
  videoId: string;
  onClose: () => void;
}) {
  const [meta, setMeta] = useState<VideoMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.fetchVideoMetadata(videoId)
      .then((d) => { setMeta(d); setLoading(false); })
      .catch((err) => { setError(err.message); setLoading(false); });
  }, [videoId]);

  const vs = meta?.video_streams?.[0];
  const a_s = meta?.audio_streams?.[0];
  const dev = meta?.device;
  const ts = meta?.timestamps;

  return (
    <div className="absolute right-0 top-10 z-50 w-[420px] max-h-[80vh] overflow-y-auto rounded-2xl bg-white shadow-2xl border border-gray-200"
         onClick={(e) => e.stopPropagation()}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <h3 className="font-bold text-gray-900 text-sm">视频信息</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
          <IconClose />
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-sm text-gray-400">
          <svg className="w-5 h-5 mr-2 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          加载中...
        </div>
      ) : error ? (
        <div className="px-5 py-8 text-sm text-gray-400 text-center">{error}</div>
      ) : !meta ? (
        <div className="px-5 py-8 text-sm text-gray-400 text-center">暂无元数据</div>
      ) : (
        <div className="px-5 py-3 space-y-4 text-sm">
          {/* Format section */}
          <Section title="文件格式">
            <Row label="容器" value={meta.container ?? "—"} />
            <Row label="时长" value={meta.duration != null ? fmtDuration(meta.duration) : "—"} />
            <Row label="文件大小" value={meta.file_size != null ? formatBytes(meta.file_size) : "—"} />
            {meta.overall_bitrate != null && (
              <Row label="总码率" value={`${(meta.overall_bitrate / 1000).toFixed(0)} kbps`} />
            )}
          </Section>

          {/* Video stream */}
          {vs && (
            <Section title="视频流">
              <Row label="编码" value={vs.codec ?? "—"} />
              {vs.codec_profile && <Row label="编码配置" value={vs.codec_profile} />}
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

          {/* Audio stream */}
          {a_s && (
            <Section title="音频流">
              <Row label="编码" value={a_s.codec ?? "—"} />
              {a_s.channels != null && <Row label="声道" value={formatChannels(a_s.channels, a_s.channel_layout ?? undefined)} />}
              {a_s.sample_rate != null && <Row label="采样率" value={`${(a_s.sample_rate / 1000).toFixed(0)} kHz`} />}
              {a_s.bitrate != null && <Row label="码率" value={`${(a_s.bitrate / 1000).toFixed(0)} kbps`} />}
              {a_s.language && <Row label="语言" value={a_s.language} />}
            </Section>
          )}

          {/* Device info */}
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
      )}
    </div>
  );
}

/* ── Sub-components ── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{title}</h4>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-gray-500 text-xs shrink-0 mr-4">{label}</span>
      <span className="text-gray-800 text-xs text-right font-mono break-all">{value}</span>
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
