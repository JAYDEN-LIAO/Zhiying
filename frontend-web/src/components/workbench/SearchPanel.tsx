import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { api } from "../../services/api";
import { formatSec } from "../../utils/helpers";
import { zh } from "../../labels";
import { IconChevronDown, IconImage, IconSearch5, IconVideo } from "../icons";
import type { FaceSearchResult, SearchResults } from "../../types";

/* ════════════════════════════════════════════════════════════
   SearchPanel — 视频搜索（右下面板，交互区）
   顶层 Tab 物理隔离两种检索形态：
     【智能检索】(默认) —— 文本类范围（全部/物体/场景/车牌/动作/文字）+ 文本输入框
     【图片搜索】       —— 图片类子模式（全局搜索/人脸搜索）+ 图片上传（点击/拖拽）
   切 Tab 清空输入与图片，避免跨形态残留；API 按 Tab 分发。
   检索范围：当前工作台视频。
   ════════════════════════════════════════════════════════════ */

/* 顶层 Tab */
type PanelTab = "smart" | "image";

/* 智能检索的文本类范围 */
type TextScope = "all" | "object" | "scene" | "plate" | "action" | "ocr";

/* 图片搜索的子模式 */
type ImageScope = "globalImage" | "faceImage";

const TEXT_SCOPES: { key: TextScope; label: string; placeholder: string }[] = [
  { key: "all", label: "全部", placeholder: "输入描述，如：一个人在跑步…" },
  { key: "object", label: "物体", placeholder: "输入物体名称，如：行人、车辆…" },
  { key: "scene", label: "场景", placeholder: "输入场景描述，如：花园、街道…" },
  { key: "plate", label: "车牌", placeholder: "输入车牌号，如：京A·12345…" },
  { key: "action", label: "动作", placeholder: "输入动作描述，如：奔跑、骑车…" },
  { key: "ocr", label: "文字", placeholder: "输入画面中的文字…" },
];

const IMAGE_SCOPES: { key: ImageScope; label: string; hint: string }[] = [
  { key: "globalImage", label: "全局搜索", hint: "上传参考图，在全库中查找相似画面" },
  { key: "faceImage", label: "人脸搜索", hint: "上传人脸照片，查找包含该人物的视频" },
];

const PLACEHOLDER_FALLBACK = "输入关键词搜索视频画面";

interface HitRow {
  key: string;
  title: string; // 主标题（caption / 车牌 / OCR / 人物）
  subtitle?: string; // 副标题（类别等）
  start: number;
  end?: number | null;
  thumb: string | null;
  similarity?: number | null;
}

export function SearchPanel({
  videoId,
  onSeek,
}: {
  videoId: string;
  onSeek: (sec: number) => void;
}) {
  /* 顶层 Tab：智能检索（默认） / 图片搜索 */
  const [tab, setTab] = useState<PanelTab>("smart");
  /* 各 Tab 独立的范围选择 */
  const [textScope, setTextScope] = useState<TextScope>("all");
  const [imageScope, setImageScope] = useState<ImageScope>("globalImage");
  const [scopeOpen, setScopeOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileUrl, setFileUrl] = useState<string | null>(null); // 上传图片预览
  const [dragOver, setDragOver] = useState(false);
  const [hits, setHits] = useState<HitRow[] | null>(null); // null = 未搜索
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const textScopeDef = TEXT_SCOPES.find((s) => s.key === textScope)!;
  const imageScopeDef = IMAGE_SCOPES.find((s) => s.key === imageScope)!;
  const imageMode = tab === "image";

  const runSearch = async () => {
    if (!videoId) return;
    if (!imageMode && !query.trim()) return;
    if (imageMode && !file) return;
    setSearching(true);
    setError(null);
    try {
      let rows: HitRow[] = [];
      if (imageMode && imageScope === "globalImage") {
        /* 图片搜索 · 全局搜索：找相似画面 */
        const r = (await api.searchImage(file!, { video_ids: [videoId] })) as SearchResults;
        rows = r.results.map(toRow);
      } else if (imageMode && imageScope === "faceImage") {
        /* 图片搜索 · 人脸搜索：人脸特征比对 */
        const r = (await api.searchFace(file!, [videoId])) as FaceSearchResult[];
        rows = r.map((f, i) => ({
          key: `face-${i}`,
          title: f.identity_label,
          subtitle: "人脸",
          start: f.first_seen,
          end: f.last_seen,
          thumb: f.thumbnail_url,
          similarity: null,
        }));
      } else {
        /* 智能检索：范围 → search_types 维度约束 */
        const searchTypes =
          textScope === "plate" ? ["plate"] : textScope === "ocr" ? ["ocr"] : textScope === "object" ? ["track"] : textScope === "scene" ? ["frame"] : textScope === "action" ? ["chunk"] : undefined;
        const r = (await api.searchSemantic(query.trim(), {
          video_ids: [videoId],
          ...(searchTypes ? { search_types: searchTypes } : {}),
        })) as SearchResults;
        rows = r.results.map(toRow);
      }
      setHits(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "检索失败");
      setHits([]);
    } finally {
      setSearching(false);
    }
  };

  const applyFile = (f: File | null) => {
    setFile(f);
    /* 生成预览 URL（替换旧的） */
    setFileUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return f ? URL.createObjectURL(f) : null;
    });
  };

  const onPickFile = (e: ChangeEvent<HTMLInputElement>) => {
    applyFile(e.target.files?.[0] ?? null);
  };

  /* 拖拽上传 */
  const onDropFile = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f && f.type.startsWith("image/")) applyFile(f);
  };

  /* 移除已选图片 */
  const clearFile = () => applyFile(null);

  /* 组件卸载时释放预览 URL */
  const urlRef = useRef<string | null>(null);
  urlRef.current = fileUrl;
  useEffect(() => () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
  }, []);

  /* 切换顶层 Tab：清空输入、图片与结果（状态保持要求） */
  const switchTab = (t: PanelTab) => {
    if (t === tab) return;
    setTab(t);
    setScopeOpen(false);
    setHits(null);
    setError(null);
    setQuery("");
    applyFile(null);
  };

  /* 当前 Tab 的下拉选项集与当前值 */
  const scopeOptions = imageMode ? IMAGE_SCOPES : TEXT_SCOPES;
  const scopeValue = imageMode ? imageScopeDef.label : textScopeDef.label;
  const selectScope = (key: string) => {
    if (imageMode) setImageScope(key as ImageScope);
    else setTextScope(key as TextScope);
    setScopeOpen(false);
    setHits(null);
    setError(null);
  };

  /* 空状态提示 */
  const emptyHint = imageMode ? imageScopeDef.hint : textScopeDef.placeholder || PLACEHOLDER_FALLBACK;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-card bg-card-bg shadow-card">
      {/* 标题栏 + 顶层 Tab：智能检索（默认） | 图片搜索 */}
      <div className="flex shrink-0 items-center justify-between border-b border-border-light px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="text-primary"><IconSearch5 className="w-4 h-4" /></span>
          <p className="text-sm font-semibold text-gray-700">视频搜索</p>
        </div>
        <nav className="flex items-center gap-1 rounded-lg bg-surface p-0.5">
          {(
            [
              { key: "smart", label: "智能检索" },
              { key: "image", label: "图片搜索" },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              onClick={() => switchTab(t.key)}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                tab === t.key ? "bg-white font-medium text-primary shadow-sm" : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* 搜索范围下拉：选项随 Tab 切换（文本类 / 图片子模式） */}
      <div className="shrink-0 border-b border-border-light px-4 py-2.5">
        <div className="relative">
          <button
            onClick={() => setScopeOpen((v) => !v)}
            className="flex w-full items-center justify-between rounded-lg border border-border-light bg-surface px-3 py-1.5 text-sm transition-colors hover:border-primary/50"
          >
            <span className="text-xs text-gray-400">搜索范围</span>
            <span className="flex items-center gap-1 font-medium text-gray-700">
              {imageMode && <IconImage className="h-3.5 w-3.5" />}
              {scopeValue}
              <span className={`text-gray-400 transition-transform ${scopeOpen ? "rotate-180" : ""}`}>
                <IconChevronDown />
              </span>
            </span>
          </button>
          {scopeOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setScopeOpen(false)} />
              <ul className="absolute left-0 right-0 top-full z-20 mt-1 grid grid-cols-2 gap-0.5 overflow-hidden rounded-lg border border-border-light bg-white p-1.5 shadow-lg">
                {scopeOptions.map((s) => (
                  <li key={s.key}>
                    <button
                      onClick={() => selectScope(s.key)}
                      title={"hint" in s ? s.hint : s.placeholder}
                      className={`flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-center text-xs transition-colors ${
                        (imageMode ? imageScope === s.key : textScope === s.key)
                          ? "bg-primary-soft font-medium text-primary"
                          : "text-gray-600 hover:bg-surface"
                      }`}
                    >
                      {"hint" in s ? <IconImage className="h-3.5 w-3.5" /> : null}
                      {s.label}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      {/* ── 智能检索：文本输入框 + 搜索按钮 ── */}
      {!imageMode && (
        <div className="shrink-0 border-b border-border-light p-3 pb-2.5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void runSearch();
            }}
            className="flex items-center gap-2"
          >
            <div className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border border-border-light bg-surface px-3 focus-within:border-primary/50">
              <IconSearch5 className="w-4 h-4 shrink-0 text-gray-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={textScopeDef.placeholder}
                className="min-w-0 flex-1 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400"
              />
            </div>
            <button type="submit" disabled={!query.trim() || searching} className="g-btn g-btn-primary h-9 shrink-0">
              搜索
            </button>
          </form>
        </div>
      )}

      {/* ── 图片搜索：大虚线上传区（点击/拖拽）→ 缩略图 + 开始搜索 ── */}
      {imageMode && (
        <div className="shrink-0 border-b border-border-light p-3 pb-2.5">
          <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={onPickFile} />
          {file && fileUrl ? (
            /* 已选图片：缩略图 + 文件信息 + 移除 + 开始搜索 */
            <div className="flex items-center gap-3">
              <div className="relative h-20 w-20 shrink-0">
                <img src={fileUrl} alt="检索图片" className="h-full w-full rounded-lg border border-border-light object-cover" />
                <button
                  onClick={clearFile}
                  title="移除图片"
                  className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-700 text-xs text-white shadow hover:bg-red-500"
                >
                  ×
                </button>
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-gray-700">{file.name}</p>
                <p className="mt-0.5 text-xs text-gray-400">{(file.size / 1024).toFixed(0)} KB</p>
              </div>
              <button
                onClick={() => void runSearch()}
                disabled={searching}
                className="g-btn g-btn-primary h-9 shrink-0"
              >
                {searching ? "搜索中…" : "开始搜索"}
              </button>
            </div>
          ) : (
            /* 未选图片：大虚线上传区（支持点击 + 拖拽），提示随子模式变化 */
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDropFile}
              className={`flex w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed py-6 transition-colors ${
                dragOver ? "border-primary bg-primary-soft/40" : "border-border-light bg-surface hover:border-primary/50 hover:bg-primary-soft/30"
              }`}
            >
              <IconImage className="h-8 w-8 text-gray-300" />
              <span className="text-sm text-gray-500">点击或拖拽图片到此处</span>
              <span className="text-xs text-gray-400">{imageScopeDef.hint}</span>
            </div>
          )}
        </div>
      )}

      {/* 核心操作区 */}
      <div className="flex min-h-0 flex-1 flex-col">
        {searching ? (
          <div className="flex flex-1 items-center justify-center">
            <p className="text-sm text-gray-400">检索中…</p>
          </div>
        ) : hits === null ? (
          /* 空状态：大放大镜 + 提示文案 */
          <div className="flex flex-1 flex-col items-center justify-center gap-3">
            <IconSearch5 className="h-14 w-14 text-gray-300" />
            <p className="text-sm text-gray-400">{emptyHint}</p>
          </div>
        ) : hits.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6">
            <p className="text-center text-sm text-gray-400">{error ?? "未找到相关结果"}</p>
          </div>
        ) : (
          <ul className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto p-2">
            {hits.map((h) => (
              <li
                key={h.key}
                onClick={() => onSeek(h.start)}
                title="点击定位到画面"
                className="flex cursor-pointer items-center gap-3 rounded-lg border border-border-light bg-surface px-2.5 py-2 transition-colors hover:border-primary/40"
              >
                <HitThumb thumb={h.thumb} title={h.title} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-gray-800">{h.title}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {h.subtitle ? `${h.subtitle} · ` : ""}
                    {formatSec(h.start)}
                    {h.end != null ? ` - ${formatSec(h.end)}` : ""}
                  </p>
                </div>
                {h.similarity != null && (
                  <span className="shrink-0 rounded bg-primary-soft px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-primary">
                    {(h.similarity * 100).toFixed(0)}%
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* SearchResultItem → 统一行结构 */
function toRow(r: {
  scene_id: number;
  scene_index: number;
  precision_level: string;
  caption: string | null;
  ocr_text: string | null;
  plate_text?: string | null;
  class_name?: string | null;
  display_seq?: number | null;
  scene_range_start: number;
  scene_range_end: number | null;
  precise_start: number | null;
  thumbnail_url: string | null;
  similarity: number | null;
}): HitRow {
  const title =
    r.plate_text ?? r.ocr_text ?? r.caption ?? (r.class_name ? `${zh(r.class_name)} #${r.display_seq ?? 1}` : "命中片段");
  const subtitle =
    r.plate_text ? "车牌" : r.ocr_text ? "文字" : r.class_name ? zh(r.class_name) : r.precision_level === "frame" ? "场景" : "片段";
  return {
    key: `${r.scene_id}-${r.scene_index}`,
    title,
    subtitle,
    start: r.precise_start ?? r.scene_range_start,
    end: r.scene_range_end,
    thumb: r.thumbnail_url,
    similarity: r.similarity,
  };
}

/* 命中缩略图：无图时显示浅色占位 */
function HitThumb({ thumb, title }: { thumb: string | null; title: string }) {
  const [failed, setFailed] = useState(false);
  if (!thumb || failed) {
    return (
      <div className="flex h-12 w-[72px] shrink-0 items-center justify-center rounded-md bg-primary-soft">
        <IconVideo className="h-5 w-5 text-primary/50" />
      </div>
    );
  }
  return <img src={thumb} alt={title} onError={() => setFailed(true)} className="h-12 w-[72px] shrink-0 rounded-md object-cover" />;
}
