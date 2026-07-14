/* ════════════════════════════════════════════════════════════
   Dashboard — Cerno 视觉工作台
   保留原设计配色 / 布局 / 玻璃面板风格，连接真实后端 API
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "./services/api";
import { PIPELINE_STAGES } from "./mockData";
import type { PipelineStage } from "./mockData";
import type {
  VideoListItem,
  VideoResponse,
  SearchResultItem,
} from "./types";

/* ════════════════════════════════════════════════════════════
   Helpers
   ════════════════════════════════════════════════════════════ */

function fmtDuration(sec: number | null): string {
  if (sec == null) return "--:--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formatSec(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* ════════════════════════════════════════════════════════════
   Inline SVG Icons
   ════════════════════════════════════════════════════════════ */

function IconEye() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconDashboard() {
  return (
    <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
      <path d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
    </svg>
  );
}

function IconHistory() {
  return (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function IconGear() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  );
}

function IconQC() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function IconSegment() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function IconCaption() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconAlign() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h16M4 8h12M4 12h16M4 16h12M4 20h16" />
    </svg>
  );
}

function IconEmbed() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  );
}

function IconSummary() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  );
}

function IconSearch() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function IconImageSearch() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

function IconPlay() {
  return (
    <svg className="w-12 h-12 text-white/80" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}


/* ════════════════════════════════════════════════════════════
   Left Sidebar
   ════════════════════════════════════════════════════════════ */

function LeftSidebar({
  showHistory,
  onToggleHistory,
  onUpload,
}: {
  showHistory: boolean;
  onToggleHistory: () => void;
  onUpload: () => void;
}) {
  return (
    <aside className="w-20 bg-white rounded-t-[40px] rounded-b-[40px] shadow-[2px_0_12px_rgba(0,0,0,0.04)] flex flex-col items-center pt-8 pb-6 z-10 flex-shrink-0 my-4 ml-4">
      <div className="mb-14">
        <div className="w-8 h-8 bg-blue-500 rounded flex items-center justify-center text-white">
          <IconEye />
        </div>
      </div>
      <nav className="flex-1 flex flex-col gap-6 w-full px-4">
        <button className="w-full aspect-square rounded-xl flex items-center justify-center transition-colors">
          <div className="w-9 h-9 bg-blue-100/50 rounded-lg flex items-center justify-center text-blue-600">
            <IconDashboard />
          </div>
        </button>
        <button
          onClick={onToggleHistory}
          className="w-full aspect-square rounded-xl flex items-center justify-center transition-colors text-gray-400 hover:bg-white/40 hover:text-gray-700"
        >
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center transition-colors ${showHistory ? "bg-blue-100/50 text-blue-600" : ""}`}>
            <IconHistory />
          </div>
        </button>
        <button
          onClick={onUpload}
          className="w-full aspect-square rounded-xl flex items-center justify-center transition-colors"
        >
          <div className="w-9 h-9 rounded-lg flex items-center justify-center text-blue-500 bg-blue-50/60 hover:bg-blue-100/80 transition-colors">
            <IconPlus />
          </div>
        </button>
      </nav>
      <div className="mt-auto flex flex-col items-center">
        <button className="w-10 h-10 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 transition-colors">
          <IconGear />
        </button>
      </div>
    </aside>
  );
}

/* ════════════════════════════════════════════════════════════
   PipelineBar — 蓝→青绿分段进度条
   ════════════════════════════════════════════════════════════ */

const stageColors: Record<PipelineStage["id"], string> = {
  qc:      "#4785f0",   // 蓝
  segment: "#4f93ed",
  align:   "#5ca8e8",   // 蓝青
  caption: "#67c4c0",   // 青色
  embed:   "#60c9a8",   // 青绿
  summary: "#55c890",   // 绿色
};

function PipelineBar({ progress }: { progress: number }) {
  return (
    <div className="glass-panel rounded-2xl px-5 py-4 border border-gray-200/60 w-full">
      {/* 分段填充条 */}
      <div className="flex gap-1 h-2 w-full">
        {PIPELINE_STAGES.map((stage) => {
          const isDone = progress >= stage.progressEnd;
          const isActive = !isDone && progress >= stage.progressStart;
          const internalPct = isDone ? 100 : isActive
            ? Math.round(((progress - stage.progressStart) / (stage.progressEnd - stage.progressStart)) * 100)
            : 0;
          const c = stageColors[stage.id];

          return (
            <div
              key={stage.id}
              className="flex-1 rounded-full overflow-hidden relative"
              style={{ backgroundColor: 'rgba(182,210,235,0.3)' }}
            >
              <div
                className="absolute inset-0 rounded-full transition-all duration-700 ease-out"
                style={{
                  width: `${internalPct}%`,
                  background: internalPct > 0
                    ? `linear-gradient(90deg, ${c}cc, ${c})`
                    : 'transparent',
                }}
              />
              {isActive && internalPct > 0 && (
                <div
                  className="absolute top-0 bottom-0 w-2 rounded-full transition-all duration-700 z-10"
                  style={{
                    left: `${internalPct}%`,
                    transform: 'translateX(-50%)',
                    background: c,
                    boxShadow: `0 0 6px ${c}`,
                  }}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* 阶段标签 + 微连接点 */}
      <div className="flex justify-between px-0.5 mt-1.5">
        {PIPELINE_STAGES.map((stage) => {
          const isDone = progress >= stage.progressEnd;
          const isActive = !isDone && progress >= stage.progressStart;
          const isPending = progress < stage.progressStart;

          return (
            <div key={stage.id} className="flex-1 flex flex-col items-center gap-1">
              {isPending && <div className="w-1 h-1 rounded-full bg-gray-300/50" />}
              {isDone && <div className="w-1 h-1 rounded-full bg-green-400/60" />}
              {isActive && <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: stageColors[stage.id], boxShadow: `0 0 4px ${stageColors[stage.id]}` }} />}
              <span className={`text-[11px] font-medium whitespace-nowrap transition-colors duration-500 ${
                isDone ? "text-gray-700" : isActive ? "font-semibold" : "text-gray-400"
              }`}
                style={isActive ? { color: stageColors[stage.id] } : {}}
              >
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   VideoSummaryCard — 连接后端 API
   ════════════════════════════════════════════════════════════ */

function VideoSummaryCard({ video }: { video: VideoResponse | null }) {
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

  const summary = video.summary;
  if (!summary) {
    return (
      <div className={containerClass}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">视频摘要</h3>
        <div className="flex-1 flex items-center justify-center">
          <span className="text-gray-400 text-sm">暂无摘要数据</span>
        </div>
      </div>
    );
  }

  return (
    <div className={containerClass}>
      <h3 className="font-bold text-gray-900 text-lg mb-2 shrink-0">视频摘要</h3>

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
                {/* Thumbnail */}
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

/* ════════════════════════════════════════════════════════════
   VideoSearchCard — 连接后端 API
   ════════════════════════════════════════════════════════════ */

function VideoSearchCard({
  currentVideoId,
  onSeekTo,
}: {
  currentVideoId: string | null;
  onSeekTo?: (start: number, end: number | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setResults([]);
    setSearching(true);
    setError(null);
    try {
      const data = await api.searchSemantic(query.trim(), {
        video_ids: currentVideoId ? [currentVideoId] : undefined,
      });
      setResults(data.results ?? []);
      setHasSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "搜索失败");
    } finally {
      setSearching(false);
    }
  }, [query, currentVideoId]);

  const resultCount = results.length;

  return (
    <div className="card-surface rounded-2xl p-4 border border-gray-200/60 flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div>
          <h3 className="font-bold text-gray-900 text-base">视频搜索</h3>
        </div>
        {resultCount > 0 && (
          <span className="text-[11px] text-gray-400 font-mono bg-gray-50 px-2 py-0.5 rounded-full">
            {resultCount} 条
          </span>
        )}
      </div>

      {/* Search Input */}
      <div className="relative mb-3 shrink-0">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          <IconSearch />
        </span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="搜索场景内容..."
          className="w-full pl-9 pr-20 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm
                     focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-300
                     outline-none transition-all placeholder:text-gray-400"
        />
        <button
          onClick={handleSearch}
          disabled={searching || !query.trim()}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 px-3.5 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg
                     hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-sm"
        >
          {searching ? (
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              搜索中
            </span>
          ) : "搜索"}
        </button>
      </div>

      {/* Results Area */}
      <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 min-h-0">
        {/* Error */}
        {error && (
          <div className="p-3 rounded-xl bg-red-50 border border-red-100 text-xs text-red-600">{error}</div>
        )}

        {/* Empty results after search */}
        {hasSearched && !error && results.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <svg className="w-10 h-10 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p className="text-sm">未找到匹配结果</p>
            <p className="text-xs mt-0.5">试试其他关键词</p>
          </div>
        )}

        {/* Results list */}
        {results.map((item, idx) => (
          <div
            key={item.scene_id || idx}
            className="p-3 bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md hover:border-blue-200 transition-all cursor-pointer"
            onClick={() => {
              const ts = item.precise_start ?? item.scene_range_start;
              if (onSeekTo && ts > 0) onSeekTo(ts, item.precise_end ?? item.scene_range_end);
            }}
          >
            <div className="flex items-start gap-3">
              {/* Thumbnail */}
              <div className="shrink-0 w-[68px] h-[51px] rounded-lg overflow-hidden bg-gray-50 border border-gray-200">
                {item.thumbnail_url ? (
                  <img
                    src={item.thumbnail_url}
                    alt=""
                    className="w-full h-full object-cover"
                    loading="lazy"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <svg className="w-5 h-5 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
                      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" />
                      <polyline points="21 15 16 10 5 21" />
                    </svg>
                  </div>
                )}
              </div>

              {/* Content */}
              <div className="min-w-0 flex-1">
                {/* Time + Score row */}
                <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                  {/* Precision time */}
                  {item.precise_start != null ? (
                    <span className="text-[11px] font-mono text-blue-500 font-medium">
                      @ {formatSec(item.precise_start)}
                      {item.precise_end != null && item.precise_end !== item.precise_start
                        ? ` — ${formatSec(item.precise_end)}`
                        : ""}
                    </span>
                  ) : (
                    <span className="text-[11px] font-mono text-gray-400">
                      {formatSec(item.scene_range_start)} — {formatSec(item.scene_range_end)}
                    </span>
                  )}

                  {/* Similarity */}
                  {item.similarity != null && (
                    <span className="text-[11px] font-mono text-blue-600 font-semibold">
                      {Math.round(item.similarity * 100)}%
                    </span>
                  )}

                  {/* Precision badge */}
                  {item.precision_level && item.precision_level !== "scene" && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-400 font-medium">
                      {item.precision_level === "frame" ? "帧定位"
                        : item.precision_level === "chunk" ? "段落"
                        : item.precision_level}
                    </span>
                  )}
                </div>

                {/* Caption */}
                {item.caption && (
                  <p className="text-xs text-gray-600 leading-relaxed line-clamp-2 mt-1">{item.caption}</p>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Initial state */}
        {!hasSearched && !searching && !error && (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <svg className="w-10 h-10 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p className="text-sm text-gray-400">输入关键词搜索视频画面</p>
            <p className="text-xs text-gray-300 mt-0.5">支持场景描述、物体名称、动作等</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   HistoryPanel — 视频历史列表
   ════════════════════════════════════════════════════════════ */

function HistoryPanel({
  videos,
  currentVideoId,
  loading,
  onSelect,
  onDelete,
  onClose,
}: {
  videos: VideoListItem[];
  currentVideoId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}) {
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  const handleDelete = async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try {
      await api.deleteVideo(id);
      onDelete(id);
    } catch {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-20" onClick={onClose} />
      <div className="absolute left-0 top-0 h-full w-[320px] bg-white shadow-xl z-30 flex flex-col animate-slide-in-right rounded-r-[20px]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <h2 className="font-bold text-gray-900 text-base">历史记录</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <IconClose />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-2">
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="animate-pulse bg-gray-50 rounded-xl p-3">
                  <div className="aspect-video rounded-lg bg-gray-100" />
                  <div className="h-3 bg-gray-100 rounded w-3/4 mt-2" />
                </div>
              ))}
            </div>
          ) : videos.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-sm text-gray-500 mt-2">暂无视频</p>
            </div>
          ) : (
            videos.map((item) => (
              <div
                key={item.id}
                onClick={() => onSelect(item.id)}
                className={`rounded-xl cursor-pointer transition-all duration-200 overflow-hidden ${
                  deletingIds.has(item.id) ? "opacity-0 -translate-x-full scale-95" : ""
                } ${
                  currentVideoId === item.id
                    ? "bg-blue-50 border border-blue-200"
                    : "hover:bg-gray-50 border border-transparent"
                } p-3`}
              >
                <div className="flex items-start gap-3">
                  <div className="w-[72px] aspect-video rounded-lg shrink-0 bg-gradient-to-br from-gray-100 to-gray-50 flex items-center justify-center overflow-hidden">
                    <span className="text-[10px] text-gray-400">视频</span>
                  </div>
                  <div className="min-w-0 flex-1 self-stretch flex flex-col justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-gray-900 truncate">{item.file_name}</h3>
                      <span className={`text-xs font-medium ${item.status === "completed" ? "text-green-600" : item.status === "processing" ? "text-blue-600" : "text-gray-400"}`}>
                        {item.status === "completed" ? "已完成" : item.status === "processing" ? "处理中" : "等待中"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-[10px] text-gray-400">{fmtDate(item.created_at)}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }}
                        className="text-gray-300 hover:text-red-500 transition-colors"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}

/* ════════════════════════════════════════════════════════════
   Main Dashboard
   ════════════════════════════════════════════════════════════ */

export default function Dashboard() {
  const [currentVideoId, setCurrentVideoId] = useState<string | null>(null);
  const [currentVideo, setCurrentVideo] = useState<VideoResponse | null>(null);
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [listKey, setListKey] = useState(0);
  const [seekTarget, setSeekTarget] = useState<{ start: number; end: number | null } | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const isProcessing = currentVideo?.status === "processing" || currentVideo?.status === "pending";
  const isCompleted = currentVideo?.status === "completed";

  /* ── Fetch video list ── */
  useEffect(() => {
    setListLoading(true);
    api.listVideos()
      .then((data) => setVideos(data ?? []))
      .catch(() => {})
      .finally(() => setListLoading(false));
  }, [listKey]);

  /* ── Fetch video detail on select ── */
  useEffect(() => {
    if (!currentVideoId) {
      setCurrentVideo(null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const fetchVideo = async () => {
      try {
        const data = await api.getVideo(currentVideoId);
        if (!cancelled) {
          setCurrentVideo(data);
          if (data.status !== "processing" && data.status !== "pending") {
            if (timer) clearInterval(timer);
          }
        }
      } catch {
        // silently retry
      }
    };

    fetchVideo();
    timer = setInterval(fetchVideo, 3000);

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [currentVideoId]);

  /* ── Seek to time ── */
  useEffect(() => {
    if (!seekTarget || !videoRef.current) return;
    videoRef.current.currentTime = seekTarget.start;
    videoRef.current.play().catch(() => {});
  }, [seekTarget]);

  /* ── Handlers ── */
  const handleSelect = useCallback((id: string) => {
    setCurrentVideoId(id);
    setCurrentVideo(null);
    setShowHistory(false);
  }, []);

  const handleDelete = useCallback((deletedId: string) => {
    if (currentVideoId === deletedId) {
      setCurrentVideoId(null);
      setCurrentVideo(null);
    }
  }, [currentVideoId]);

  const handleUpload = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const result = await api.upload(file);
        setCurrentVideoId(result.id);
        setCurrentVideo(result);
        setListKey((k) => k + 1);
      } catch (err) {
        alert(err instanceof Error ? err.message : "上传失败");
      }
    };
    input.click();
  }, []);

  /* ── Stats ── */
  const statLabel = currentVideo?.file_name ?? "等待选择";
  const statValue = currentVideo?.duration != null ? fmtDuration(currentVideo.duration) : "—";
  const sceneCount = currentVideo?.summary?.scenes_summary?.length ?? null;

  return (
    <div className="dashboard-container relative h-screen">
      <div className="fluid-blob fluid-blob-blue" />
      <div className="fluid-blob fluid-blob-green" />
      <div className="fluid-blob fluid-blob-warm" />

      {/* Separator + search + bulb */}
      <div className="absolute left-[128px] right-0 top-[80px] z-20">
        <div className="h-px bg-gray-300/60 w-full" />
        <div className="absolute -top-[54px]" style={{ right: '156px' }}>
          <div className="relative">
            <svg className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              className="h-8 w-72 pl-10 pr-4 bg-gray-200/70 backdrop-blur-sm border-none rounded-full focus:ring-2 focus:ring-blue-100 text-sm placeholder-gray-500 outline-none"
              placeholder="全局搜索..."
              type="text"
            />
          </div>
        </div>
      </div>

      <LeftSidebar
        showHistory={showHistory}
        onToggleHistory={() => setShowHistory((v) => !v)}
        onUpload={handleUpload}
      />

      {/* Main Content */}
      <main className="flex-1 flex flex-col relative z-10">
        <div className="flex-1 pt-[23px] pl-8 pr-4 flex flex-col">
          {/* Title + Stat Cards */}
          <div className="flex items-start">
            <h1 className="text-4xl font-bold text-gray-900 leading-tight tracking-tighter whitespace-nowrap shrink-0">工作台</h1>
            {currentVideo ? (
              <div className="flex mt-2 ml-auto">
                <div className="flex items-start gap-3">
                  <div className="w-0.5 h-8 mt-0.5 bg-gray-300 rounded-full flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{statLabel}</p>
                    <p className="text-gray-500 text-sm font-mono">{statValue}</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex mt-2 ml-auto">
                <div className="flex items-start gap-3">
                  <div className="w-0.5 h-8 mt-0.5 bg-gray-300 rounded-full flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">等待选择</p>
                    <p className="text-gray-500 text-sm font-mono">—</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="mt-2 mb-4" />

          {/* Video Player Area */}
          <div className="relative w-full aspect-video rounded-2xl overflow-hidden bg-black/5 shadow-inner flex items-center justify-center">
            {currentVideoId && currentVideo ? (
              <video
                ref={videoRef}
                key={currentVideoId}
                className="w-full h-full object-contain bg-black"
                src={api.getVideoStreamUrl(currentVideoId)}
                controls
                autoPlay={false}
                preload="auto"
                playsInline
              >
                您的浏览器不支持视频播放
              </video>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <div className="w-16 h-16 rounded-full bg-black/40 flex items-center justify-center shadow-lg">
                  <IconPlay />
                </div>
                <p className="text-sm text-gray-400">上传或选择视频开始</p>
              </div>
            )}
          </div>

          {/* Pipeline Bar — 分段光谱进度 */}
          <div className="mt-10 w-full">
            <PipelineBar progress={currentVideo?.progress ?? 0} />
          </div>
        </div>
      </main>

      {/* Right Sidebar */}
      <aside className="w-[460px] p-4 pt-[96px] pb-4 flex flex-col gap-3 z-10 flex-shrink-0 h-full">
        <div className="flex-1 min-h-0">
          <VideoSummaryCard video={currentVideo} />
        </div>
        <div className="flex-1 min-h-0">
          <VideoSearchCard currentVideoId={currentVideoId} onSeekTo={(start, end) => setSeekTarget({ start, end })} />
        </div>
      </aside>

      {/* History Panel */}
      {showHistory && (
        <HistoryPanel
          videos={videos}
          currentVideoId={currentVideoId}
          loading={listLoading}
          onSelect={handleSelect}
          onDelete={handleDelete}
          onClose={() => setShowHistory(false)}
        />
      )}
    </div>
  );
}
