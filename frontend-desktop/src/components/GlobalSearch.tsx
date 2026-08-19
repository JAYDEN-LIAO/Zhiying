/* ════════════════════════════════════════════════════════════
   GlobalSearch — 全局搜索（v0.38）
   跨文件夹语义检索 / 以图搜图。经典左右分栏：
     左 34% 检索配置（文本/图像 Tab + Smart Chips + 范围 + 开始）
     右 66% 结果展示（状态栏 + 自适应卡片网格）
   ════════════════════════════════════════════════════════════ */

import { useMemo, useRef, useState } from "react";
import { api } from "../services/api";
import { useApp } from "../AppContext";
import type { SearchResultItem, VideoListItem } from "../types";
import { formatSec, fmtFullDate } from "../utils/helpers";
import { zh } from "../labels";
import { IconSearch5, IconImageSearch, IconFolder, IconClock, IconClose, IconVideo, IconRetry, IconSort, IconExternal, IconImage, IconDownload } from "./icons";

type TabKey = "text" | "image";
type ChipGroup = "type" | "color" | "time" | "duration";
type SortKey = "time" | "confidence" | "name";

interface ChipDef {
  key: string;
  label: string;
  token: string;
  group: ChipGroup;
  color?: string;
}

interface ChipGroupDef {
  id: ChipGroup;
  label: string;
  single?: boolean;
  items: ChipDef[];
}

const CHIP_GROUPS: ChipGroupDef[] = [
  {
    id: "type",
    label: "目标类型",
    single: true,
    items: [
      { key: "person", label: "行人", token: "type:行人", group: "type" },
      { key: "vehicle", label: "机动车", token: "type:机动车", group: "type" },
      { key: "bike", label: "非机动车", token: "type:非机动车", group: "type" },
    ],
  },
  {
    id: "color",
    label: "颜色特征",
    items: [
      { key: "red", label: "红色", token: "color:红色", group: "color", color: "#f04444" },
      { key: "orange", label: "橙色", token: "color:橙色", group: "color", color: "#ff8f2b" },
      { key: "yellow", label: "黄色", token: "color:黄色", group: "color", color: "#f7c948" },
      { key: "green", label: "绿色", token: "color:绿色", group: "color", color: "#36b37e" },
      { key: "blue", label: "蓝色", token: "color:蓝色", group: "color", color: "#4f6ef7" },
      { key: "purple", label: "紫色", token: "color:紫色", group: "color", color: "#9b59d0" },
      { key: "white", label: "白色", token: "color:白色", group: "color", color: "#e8ebf2" },
      { key: "black", label: "黑色", token: "color:黑色", group: "color", color: "#3b4252" },
      { key: "gray", label: "灰色", token: "color:灰色", group: "color", color: "#8a94a6" },
    ],
  },
  {
    id: "time",
    label: "时间段",
    single: true,
    items: [
      { key: "24h", label: "近24小时", token: "time:近24小时", group: "time" },
      { key: "7d", label: "近7天", token: "time:近7天", group: "time" },
      { key: "custom", label: "自定义", token: "time:自定义", group: "time" },
    ],
  },
  {
    id: "duration",
    label: "文件时长",
    single: true,
    items: [
      { key: "le60", label: "≤1分钟", token: "duration:≤60s", group: "duration" },
      { key: "60_300", label: "1-5分钟", token: "duration:60-300s", group: "duration" },
      { key: "ge300", label: "≥5分钟", token: "duration:≥300s", group: "duration" },
      { key: "dur_custom", label: "自定义", token: "duration:自定义", group: "duration" },
    ],
  },
];

const PRECISION_LABEL: Record<string, string> = {
  plate: "车牌",
  track: "物体",
  text: "文字",
  label: "标签",
  scene: "画面",
  chunk: "片段",
  frame: "画面",
};

/* 胶囊色调：按目标类型分配不同颜色背景 */
const TAG_TONES: Record<string, string> = {
  行人: "blue",
  机动车: "indigo",
  车辆: "indigo",
  非机动车: "cyan",
  车牌: "purple",
  文字: "amber",
  物体: "teal",
  画面: "slate",
  片段: "slate",
  标签: "slate",
};

/* 从识别描述中提取颜色特征（如「红衣」→「红色」） */
const COLOR_WORDS: [string, string][] = [
  ["红色", "红色"],
  ["红衣", "红色"],
  ["橙色", "橙色"],
  ["黄色", "黄色"],
  ["绿色", "绿色"],
  ["蓝色", "蓝色"],
  ["紫色", "紫色"],
  ["白色", "白色"],
  ["黑色", "黑色"],
  ["灰色", "灰色"],
  ["粉色", "粉色"],
];

export function GlobalSearch() {
  const { videos, videoGroups, openWorkbench } = useApp();

  const [tab, setTab] = useState<TabKey>("text");
  const [query, setQuery] = useState("");
  const [chips, setChips] = useState<Set<string>>(new Set());
  const [timeStart, setTimeStart] = useState("");
  const [timeEnd, setTimeEnd] = useState("");
  const [durCustom, setDurCustom] = useState("");
  const [folderIds, setFolderIds] = useState<Set<string>>(new Set());
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [similarity, setSimilarity] = useState(0.5);
  const [dragOver, setDragOver] = useState(false);

  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [libCount, setLibCount] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);

  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const videoMap = useMemo(() => new Map(videos.map((v) => [v.id, v])), [videos]);
  const groupNameMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of videoGroups) m.set(g.groupId, g.name ?? g.number ?? "未命名文件夹");
    return m;
  }, [videoGroups]);

  /* ── Smart Chip：追加/移除语法 token（单选组互斥，颜色可多选）── */
  function applyToken(q: string, def: ChipDef): string {
    const parts = q.split(/\s+/).filter(Boolean);
    const prefix = def.token.split(":")[0] + ":";
    if (def.group === "color") {
      const i = parts.indexOf(def.token);
      if (i >= 0) parts.splice(i, 1);
      else parts.push(def.token);
    } else {
      const idx = parts.findIndex((p) => p.startsWith(prefix));
      if (idx >= 0) {
        if (parts[idx] === def.token) parts.splice(idx, 1);
        else parts[idx] = def.token;
      } else parts.push(def.token);
    }
    return parts.join(" ");
  }

  function toggleChip(def: ChipDef) {
    setQuery((q) => applyToken(q, def));
    setChips((prev) => {
      const next = new Set(prev);
      if (def.group === "color") {
        if (next.has(def.key)) next.delete(def.key);
        else next.add(def.key);
      } else {
        for (const g of CHIP_GROUPS)
          if (g.id === def.group) for (const i of g.items) next.delete(i.key);
        if (!prev.has(def.key)) next.add(def.key);
      }
      return next;
    });
  }

  /* ── 检索范围：文件夹多选 + 时间段 + 时长 → 视频 id 集合 ── */
  function buildScopeIds(): string[] | undefined {
    let pool = videos;
    const hasFilter =
      folderIds.size > 0 ||
      chips.has("24h") ||
      chips.has("7d") ||
      chips.has("custom") ||
      chips.has("le60") ||
      chips.has("60_300") ||
      chips.has("ge300") ||
      chips.has("dur_custom");
    if (!hasFilter) return undefined;

    if (folderIds.size > 0) {
      const gids = new Set(folderIds);
      pool = pool.filter((v) => v.group_id && gids.has(v.group_id));
    }
    const now = Date.now();
    let cutoff: number | null = null;
    if (chips.has("24h")) cutoff = now - 24 * 3600 * 1000;
    else if (chips.has("7d")) cutoff = now - 7 * 24 * 3600 * 1000;
    else if (chips.has("custom") && timeStart) cutoff = new Date(timeStart).getTime();
    if (cutoff != null) pool = pool.filter((v) => new Date(v.created_at).getTime() >= cutoff);
    if (chips.has("custom") && timeEnd) {
      const endMs = new Date(timeEnd).getTime();
      pool = pool.filter((v) => new Date(v.created_at).getTime() <= endMs);
    }
    if (chips.has("le60")) pool = pool.filter((v) => v.duration != null && v.duration <= 60);
    else if (chips.has("60_300")) pool = pool.filter((v) => v.duration != null && v.duration > 60 && v.duration <= 300);
    else if (chips.has("ge300")) pool = pool.filter((v) => v.duration != null && v.duration > 300);
    else if (chips.has("dur_custom")) {
      const sec = Number(durCustom);
      if (!Number.isNaN(sec) && sec > 0) pool = pool.filter((v) => v.duration != null && v.duration >= sec);
    }
    return pool.map((v) => v.id);
  }

  async function runSearch() {
    if (tab === "text" && !query.trim()) {
      setError("请输入检索描述，或点击下方快捷标签生成语法");
      return;
    }
    if (tab === "image" && !imageFile) {
      setError("请先选择或拖入一张参考图片");
      return;
    }
    const ids = buildScopeIds();
    if (ids && ids.length === 0) {
      setResults([]);
      setTotal(0);
      setLibCount(0);
      setElapsedMs(0);
      setHasSearched(true);
      setSearching(false);
      setError("当前筛选条件下没有可检索的视频，请调整检索范围");
      return;
    }
    const t0 = performance.now();
    setSearching(true);
    setError(null);
    try {
      const res =
        tab === "text"
          ? await api.searchSemantic(query.trim(), { video_ids: ids, top_k: 60, min_similarity: 0 })
          : await api.searchImage(imageFile!, { video_ids: ids, top_k: 60, min_similarity: similarity });
      const list = res.results ?? [];
      setResults(list);
      setTotal(res.total ?? list.length);
      setElapsedMs(Math.round(res.query_time_ms ?? performance.now() - t0));
      const gs = new Set<string>();
      for (const r of list) gs.add(videoMap.get(r.video_id)?.group_id ?? "__ungrouped__");
      setLibCount(gs.size);
      setHasSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "检索失败，请稍后重试");
      setResults([]);
      setTotal(0);
      setHasSearched(true);
    } finally {
      setSearching(false);
    }
  }

  function setImage(f: File | null) {
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return f ? URL.createObjectURL(f) : null;
    });
    setImageFile(f);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f && f.type.startsWith("image/")) setImage(f);
    else if (f) setError("仅支持图片文件");
  }

  function targetTag(item: SearchResultItem): string {
    if (item.precision_level === "track" && item.class_name) return zh(item.class_name);
    if (item.precision_level === "plate" && item.plate_text) return "车牌";
    return PRECISION_LABEL[item.precision_level] ?? "目标";
  }

  function simValue(item: SearchResultItem): number {
    const s = item.confidence ?? item.similarity;
    return s == null ? -1 : Math.round(s * 100);
  }

  /* ── 排序：按置信度 / 时间 / 文件名 ── */
  const sortedResults = useMemo(() => {
    const arr = [...results];
    if (sortKey === "confidence") {
      arr.sort((a, b) => simValue(b) - simValue(a));
    } else if (sortKey === "name") {
      arr.sort((a, b) => {
        const na = videoMap.get(a.video_id)?.file_name ?? "";
        const nb = videoMap.get(b.video_id)?.file_name ?? "";
        return na.localeCompare(nb, "zh-Hans-CN");
      });
    } else {
      arr.sort((a, b) => {
        const ta = videoMap.get(a.video_id)?.created_at ?? "";
        const tb = videoMap.get(b.video_id)?.created_at ?? "";
        return tb.localeCompare(ta);
      });
    }
    return arr;
  }, [results, sortKey, videoMap]);

  function tagTone(tag: string): string {
    return TAG_TONES[tag] ?? "blue";
  }

  function extractColor(caption?: string | null): string | null {
    if (!caption) return null;
    for (const [kw, name] of COLOR_WORDS) if (caption.includes(kw)) return name;
    return null;
  }

  /* 每行标签胶囊：[目标类型] [颜色特征/车牌] [置信度] */
  function buildPills(item: SearchResultItem): { text: string; tone: string }[] {
    const pills: { text: string; tone: string }[] = [];
    const tag = targetTag(item);
    pills.push({ text: tag, tone: tagTone(tag) });
    if (item.precision_level === "plate" && item.plate_text) {
      pills.push({ text: item.plate_text, tone: "purple" });
    } else {
      const color = extractColor(item.caption);
      if (color) pills.push({ text: color, tone: "rose" });
    }
    const sim = simValue(item);
    if (sim >= 0) {
      pills.push({ text: `${sim}%`, tone: sim >= 80 ? "green" : sim >= 60 ? "amber" : "gray" });
    }
    return pills;
  }

  /* 未命名文件显示「摄像头_时间」 */
  function displayName(v?: VideoListItem): string {
    if (v?.file_name) return v.file_name;
    if (v?.created_at) return `摄像头_${fmtFullDate(v.created_at)}`;
    return "未知视频";
  }

  function downloadOriginal(videoId: string, fileName?: string) {
    const a = document.createElement("a");
    a.href = api.getVideoStreamUrl(videoId);
    a.download = fileName || `${videoId}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function batchAnalyze() {
    if (selected.size === 0 || batchBusy) return;
    setBatchBusy(true);
    try {
      await api.analyzeBatch([...selected]);
      setSelected(new Set());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "批量解析失败");
    } finally {
      setBatchBusy(false);
    }
  }

  const goDisabled = searching || (tab === "text" ? !query.trim() : !imageFile);

  return (
    <div className="gs-page">
      {/* ── 左侧：检索配置面板 ── */}
      <aside className="gs-left">
        <div className="gs-card gs-tabs">
          <button type="button" className={tab === "text" ? "on" : ""} onClick={() => setTab("text")}>
            <IconSearch5 />
            文本检索
          </button>
          <button type="button" className={tab === "image" ? "on" : ""} onClick={() => setTab("image")}>
            <IconImageSearch />
            图像检索
          </button>
        </div>

        {tab === "text" ? (
          <div className="gs-card gs-text-form">
            <textarea
              className="gs-query"
              rows={2}
              placeholder="输入自然语言描述，如：穿黄衣服骑电动车的人"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  runSearch();
                }
              }}
            />
            {query.trim() && (
              <button type="button" className="gs-clear" onClick={() => setQuery("")} title="清空">
                <IconClose />
              </button>
            )}
            <div className="gs-chips">
              {CHIP_GROUPS.map((g) => (
                <div key={g.id} className="gs-chip-group">
                  <span className="gs-chip-tt">{g.label}</span>
                  <div className="gs-chip-row">
                    {g.items.map((c) => (
                      <button
                        key={c.key}
                        type="button"
                        className={"gs-chip" + (chips.has(c.key) ? " on" : "")}
                        onClick={() => toggleChip(c)}
                      >
                        {c.color && <i className="gs-dot" style={{ background: c.color }} />}
                        {c.label}
                      </button>
                    ))}
                  </div>
                  {g.id === "time" && chips.has("custom") && (
                    <div className="gs-time-custom">
                      <input type="datetime-local" step="1" value={timeStart} onChange={(e) => setTimeStart(e.target.value)} />
                      <span>至</span>
                      <input type="datetime-local" step="1" value={timeEnd} onChange={(e) => setTimeEnd(e.target.value)} />
                    </div>
                  )}
                  {g.id === "duration" && chips.has("dur_custom") && (
                    <div className="gs-time-custom">
                      <input type="number" min={1} placeholder="秒" value={durCustom} onChange={(e) => setDurCustom(e.target.value)} />
                      <span>秒以上</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="gs-card gs-image-form">
            <div
              className={"gs-drop" + (dragOver ? " over" : "")}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
            >
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) setImage(f);
                  e.target.value = "";
                }}
              />
              {imageFile ? (
                <>
                  <img className="gs-drop-preview" src={previewUrl ?? undefined} alt="preview" />
                  <p className="gs-drop-name">{imageFile.name}</p>
                  <button
                    type="button"
                    className="gs-drop-remove"
                    onClick={(e) => {
                      e.stopPropagation();
                      setImage(null);
                    }}
                  >
                    移除
                  </button>
                </>
              ) : (
                <>
                  <div className="gs-drop-icon">
                    <IconImageSearch />
                  </div>
                  <p>拖拽图片到此处，或点击选择</p>
                  <span className="gs-drop-sub">支持 JPG / PNG / WebP，用于以图搜图</span>
                </>
              )}
            </div>
            <div className="gs-slider-row">
              <span className="gs-slider-tt">相似度阈值</span>
              <input
                className="gs-range"
                type="range"
                min={0.3}
                max={0.95}
                step={0.05}
                value={similarity}
                onChange={(e) => setSimilarity(Number(e.target.value))}
              />
              <span className="gs-slider-val">{Math.round(similarity * 100)}%</span>
            </div>
          </div>
        )}

        <div className="gs-card gs-scope">
          <div className="gs-scope-head">
            <IconFolder />
            <span>检索范围</span>
            <span className="gs-scope-count">{folderIds.size === 0 ? "全部文件夹" : `已选 ${folderIds.size} 个`}</span>
          </div>
          <div className="gs-scope-list">
            <label className={"gs-scope-item" + (folderIds.size === 0 ? " on" : "")}>
              <input type="checkbox" checked={folderIds.size === 0} onChange={() => setFolderIds(new Set())} />
              <span>全部文件夹</span>
              <em>{videoGroups.length}</em>
            </label>
            {videoGroups.map((g) => (
              <label key={g.groupId} className={"gs-scope-item" + (folderIds.has(g.groupId) ? " on" : "")}>
                <input
                  type="checkbox"
                  checked={folderIds.has(g.groupId)}
                  onChange={() => {
                    setFolderIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(g.groupId)) next.delete(g.groupId);
                      else next.add(g.groupId);
                      return next;
                    });
                  }}
                />
                <span>{g.name ?? g.number ?? "未命名文件夹"}</span>
                <em>{g.file_count ?? g.videoIds.length}</em>
              </label>
            ))}
          </div>
        </div>

        {error && (
          <div className="gs-error">
            <IconRetry className="w-4 h-4" />
            <span>{error}</span>
          </div>
        )}

        <button type="button" className="gs-go" onClick={runSearch} disabled={goDisabled}>
          {searching ? <i className="gs-spin" /> : <IconSearch5 />}
          {searching ? "全域检索中…" : "开始全域检索"}
        </button>
      </aside>

      {/* ── 右侧：检索结果展示区 ── */}
      <section className="gs-right">
        <div className="gs-toolbar">
          <div className="gs-stat">
            <span className="gs-stat-main">
              {hasSearched ? (
                <>
                  共检索到 <b>{total}</b> 个相关视频片段
                </>
              ) : (
                "尚未检索"
              )}
            </span>
            {hasSearched && (
              <span className="gs-stat-sub">
                耗时 {elapsedMs} ms · 跨越 {libCount} 个文件夹
              </span>
            )}
            {searching && <span className="gs-searching-tip">检索中，请稍候…</span>}
          </div>
          <label className="gs-sort">
            <IconSort />
            <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
              <option value="confidence">按置信度</option>
              <option value="time">按时间</option>
              <option value="name">按文件名</option>
            </select>
          </label>
        </div>

        {!hasSearched ? (
          <div className="gs-empty">
            <div className="gs-empty-icon">
              <IconSearch5 />
            </div>
            <p>选择检索方式并点击「开始全域检索」</p>
            <span className="gs-empty-sub">支持自然语言描述与以图搜图，跨所有文件夹匹配目标</span>
          </div>
        ) : results.length === 0 ? (
          <div className="gs-empty">
            <div className="gs-empty-icon muted">
              <IconClose />
            </div>
            <p>未找到匹配结果</p>
            <span className="gs-empty-sub">试试调整描述、缩短时间段或扩大检索范围</span>
          </div>
        ) : (
          <div className="gs-list">
            {sortedResults.map((r, i) => {
              const v = videoMap.get(r.video_id);
              const processing = v != null && (v.status === "processing" || v.status === "pending");
              const pct = v?.progress != null ? Math.round(v.progress * 100) : null;
              const timeSec = r.precise_start ?? r.scene_range_start;
              const groupName = v?.group_id ? groupNameMap.get(v.group_id) ?? "未命名文件夹" : "未分组";
              const pathText = `${groupName} / ${v?.file_name ?? v?.id}`;
              const isSel = selected.has(r.video_id);
              return (
                <div key={`${r.video_id}-${i}`} className={"gs-row" + (isSel ? " sel" : "")}>
                  <label className="gs-check">
                    <input type="checkbox" checked={isSel} onChange={() => toggleSelect(r.video_id)} />
                  </label>
                  <div className="gs-row-media" onClick={() => openWorkbench(r.video_id)} title="点击打开对应视频">
                    {r.thumbnail_url ? (
                      <img src={r.thumbnail_url} alt="" loading="lazy" />
                    ) : (
                      <div className="gs-thumb-fallback">
                        <IconVideo />
                      </div>
                    )}
                    <span className="gs-row-badge">{timeSec != null ? formatSec(timeSec) : <IconImage />}</span>
                    {processing && (
                      <div className="gs-row-mask">
                        <i className="gs-spin" />
                        <span>{pct != null ? `解析中 ${pct}%` : "解析中…"}</span>
                      </div>
                    )}
                  </div>
                  <div className="gs-row-info" onClick={() => openWorkbench(r.video_id)}>
                    <div className="gs-row-title" title={v?.file_name ?? r.video_id}>
                      {displayName(v)}
                    </div>
                    <div className="gs-row-tags">
                      {buildPills(r).map((p, j) => (
                        <span key={j} className={"gs-pill " + p.tone}>
                          {p.text}
                        </span>
                      ))}
                    </div>
                    <div className="gs-row-meta">
                      <span className="gs-meta-time">
                        <IconClock />
                        {v?.created_at ? fmtFullDate(v.created_at) : "--"}
                      </span>
                      <span className="gs-meta-path" title={pathText}>
                        {pathText}
                      </span>
                    </div>
                  </div>
                  <div className="gs-row-actions">
                    <button type="button" className="gs-btn-primary" onClick={() => openWorkbench(r.video_id)}>
                      进入分析平台
                      <IconExternal />
                    </button>
                    <button type="button" className="gs-btn-ghost" onClick={() => downloadOriginal(r.video_id, v?.file_name)}>
                      <IconDownload />
                      下载原片
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {selected.size > 0 && (
          <div className="gs-select-bar">
            <span className="gs-select-count">
              已选 <b>{selected.size}</b> 个
            </span>
            <button type="button" className="gs-btn-primary" onClick={batchAnalyze} disabled={batchBusy}>
              {batchBusy ? <i className="gs-spin" /> : null}
              {batchBusy ? "发送中…" : "批量发送解析"}
            </button>
            <button type="button" className="gs-btn-ghost" onClick={() => setSelected(new Set())}>
              取消
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
