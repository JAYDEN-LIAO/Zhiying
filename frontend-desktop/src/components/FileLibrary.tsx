/* ════════════════════════════════════════════════════════════
   FileLibrary — 案例库（v0.34 三卡片布局）
   拆成 3 个组件（中间留间隙、全圆角）：
     ① CaseHeader  顶部卡：案例库标题 + 新建案例
     ② CaseList    左卡：案例列表（编号/负责人/时间/文件数 + 删除）
     ③ CaseContent 右卡：案例内容（文件表格：视频 + 图片 + 上传 + 状态筛选）
   数据源 = /files + /groups + /groups/{id}/assets
   ════════════════════════════════════════════════════════════ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api";
import { useApp } from "../AppContext";
import type { FileItem, VideoGroup, CaseAssetItem, PipelineParams, VideoResponse, VideoMetadata, ProcessStatus, ParseMode } from "../types";
import { fmtDuration, fmtDate, fmtBytes } from "../utils/helpers";
import { IconFolder, IconPlus, IconPlay2, IconTrash, IconPencil, IconBolt, IconBoltSolid, IconEye, IconGrid, IconList, IconDownload, IconClose, IconInfo, IconSummary, IconRetry, IconDoc, IconPerson, IconCar, IconText, IconError, IconSearch } from "./icons";
import { useHEVCCapability } from "../hooks/useHEVCCapability";

type TreeKey = "all" | "ungrouped" | `g:${string}`;

const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待处理", cls: "wait" },
  processing: { label: "处理中", cls: "run", pulse: true },
  completed: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

/* ═══════════ 两阶段处理流状态（v0.36）═══════════
   阶段一（入库预处理）：转码 / 关键帧 / 摘要，上传后自动
   阶段二（精细化分析）：人脸 / OCR / 车牌，用户手动触发 */
const PROCESS_STATUS_META: Record<ProcessStatus, { label: string; css: string; badge: string; pulse?: boolean }> = {
  PRE_PROCESSING: { label: "预处理中", css: "pre", badge: "wait", pulse: true },
  READY_FOR_ANALYSIS: { label: "待分析", css: "ready", badge: "ready" },
  ANALYZING: { label: "分析中", css: "analyzing", badge: "run", pulse: true },
  COMPLETED: { label: "已完成", css: "completed", badge: "ok" },
  FAILED: { label: "失败", css: "failed", badge: "err" },
};

/* 两阶段状态推断：优先 process_status；后端未提供时从 current_status 降级 */
function inferProcessStatus(f: FileItem): ProcessStatus {
  if (f.process_status) return f.process_status;
  const hasSummary = !!f.current_summary?.one_liner;
  switch (f.current_status) {
    case "pending": return "PRE_PROCESSING";              // 刚上传，等待转码/摘要
    case "processing": return hasSummary ? "ANALYZING" : "PRE_PROCESSING";
    case "completed": return "READY_FOR_ANALYSIS";        // 摘要就绪、可播放；深度识别由 process_status 标记
    case "failed": return "FAILED";
    default: return "PRE_PROCESSING";
  }
}

/* ═══════════ 解析模式（v0.37）═══════════
   quick    极速概览模式：仅文本摘要，低算力，极快
   standard 标准检索模式：提取人 / 车 / 字结构化数据，中/高算力，较慢 */
function inferParseMode(f: FileItem): ParseMode {
  if (f.parse_mode === "quick" || f.parse_mode === "standard") return f.parse_mode;
  // 后端未返回模式字段时，用实体数据反推：有结构化产出 → 标准检索
  const ent = f.analysis_entities;
  if (ent && (ent.face || ent.plate || ent.ocr)) return "standard";
  return "quick";
}

const MODE_META: Record<ParseMode, { label: string; css: string }> = {
  quick: { label: "极速概览", css: "quick" },
  standard: { label: "标准检索", css: "standard" },
};

/* v0.37 识别项配置：仅标准检索模式下三项可独立开关；极速模式强制忽略 */
export type RecognitionToggles = { face: boolean; plate: boolean; ocr: boolean };
const ALL_TOGGLES: RecognitionToggles = { face: true, plate: true, ocr: true };

/* 按模式构造阶段二/入库 PipelineParams：
   极速 = 仅摘要，关闭人脸/车辆/文字/目标检测/检索索引（识别项强制全关）；
   标准 = 识别项按用户开关独立控制，供精细化研判检索使用 */
function buildParamsByMode(mode: ParseMode, toggles?: RecognitionToggles, video?: VideoResponse | null): PipelineParams {
  const std = mode === "standard";
  const t = { ...ALL_TOGGLES, ...(toggles ?? {}) };
  const anyEntity = std && (t.face || t.plate || t.ocr);
  return {
    content_type: video?.content_type ?? "general",
    vision_enabled: video?.vision_enabled ?? true,
    audio_enabled: video?.audio_enabled ?? false,
    ocr_enabled: std && t.ocr,
    caption_enabled: true,
    detection_enabled: std && (t.face || t.plate),
    detection_classes: null,
    face_enabled: std && t.face,
    plate_enabled: std && t.plate,
    search_index_enabled: anyEntity,
    summary_enabled: true,
    summary_mode: video?.summary_mode ?? "vlm_llm",
    language: video?.language ?? "auto",
    sample_fps: 1.0,
    segment_threshold: 0.5,
    caption_with_context: true,
    summary_detail: video?.summary_detail ?? "standard",
    encode_profile: null,
  };
}

/* 生成案例编号：A-YYYY-MMDD-NN，同一天自动递增（02/03…），用户可手动改 */
function genCaseNumber(groups: VideoGroup[]): string {
  const now = new Date();
  const y = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const prefix = `A-${y}-${mm}${dd}-`;
  let max = 0;
  for (const g of groups) {
    const m = g.number?.match(new RegExp(`^${prefix}(\\d{2})$`));
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `${prefix}${String(max + 1).padStart(2, "0")}`;
}

function VideoIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0 1 21 8.618v6.764a1 1 0 0 1-1.447.894L15 14M5 18h8a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2z" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 15l-5-5L5 21" />
    </svg>
  );
}

/* 从视频元数据 raw 里尽力提取 md5/checksum（后端未单独返回 md5 字段时降级为 —） */
function extractMd5(meta: VideoMetadata | null): string | null {
  const anyMeta = meta as unknown as { raw?: Record<string, unknown> } | null;
  const raw = anyMeta?.raw;
  if (!raw) return null;
  const fmt = raw.format as Record<string, unknown> | undefined;
  const tags = fmt?.tags as Record<string, unknown> | undefined;
  if (tags) {
    for (const k of Object.keys(tags)) if (/md5|checksum|hash/i.test(k)) return String(tags[k]);
  }
  for (const k of Object.keys(raw)) if (/md5|checksum/i.test(k)) return String(raw[k]);
  return null;
}

/* ═══════════════════════ ① 顶部卡 ═══════════════════════ */
function CaseHeader({ onNewCase }: { onNewCase: () => void }) {
  return (
    <div className="case-card flex items-center justify-between flex-wrap gap-y-1.5 px-5 py-2 min-h-[56px] shrink-0">
      <div>
        <h1 className="text-[16px] font-semibold text-gray-900 leading-tight">案例库</h1>
        <p className="text-[12px] text-gray-500 leading-tight">案例素材归档</p>
      </div>
      <button className="g-btn g-btn-primary" onClick={onNewCase}>
        <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 3h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" /></svg>
        新建案例
      </button>
    </div>
  );
}

/* ═══════════════════════ ② 案例列表卡 ═══════════════════════ */
function CaseList({
  groups, files, tree, onSelect, onDeleteCase,
}: {
  groups: VideoGroup[];
  files: FileItem[];
  tree: TreeKey;
  onSelect: (gid: string) => void;
  onDeleteCase: (g: VideoGroup) => void;
}) {
  return (
    <div className="w-[290px] shrink-0 case-card flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between shrink-0">
        <span className="text-[12px] font-semibold text-gray-700">案例</span>
        <span className="text-[11.5px] text-gray-500">{groups.length} 个案例</span>
      </div>
      <div className="flex-1 overflow-auto py-1.5">
        {groups.map((g) => {
          const active = tree === `g:${g.groupId}`;
          const cnt = files.filter((f) => f.group_id === g.groupId).length;
          return (
            <div key={g.groupId}
              className={"group relative mx-1.5 px-3 py-2.5 rounded-md cursor-pointer border-l-[3px] transition-all duration-150 " +
                (active ? "bg-brand/5 border-[#4f7cff] shadow-sm" : "border-transparent hover:bg-white hover:shadow-sm")}
              onClick={() => onSelect(g.groupId)}
            >
              <div className="flex items-center gap-2">
                <span className={active ? "text-[#4f7cff]" : "text-gray-400"}><IconFolder /></span>
                <span className={"text-[13px] truncate flex-1 " + (active ? "text-[#4f7cff] font-semibold" : "text-gray-800")}>{g.name || "未命名案例"}</span>
                <span className="text-[11px] text-gray-600 bg-gray-100 rounded-full px-1.5 py-0.5">{cnt}</span>
                <button className="p-1 rounded-md text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors flex-shrink-0" title="删除案例"
                  onClick={(e) => { e.stopPropagation(); onDeleteCase(g); }}>
                  <IconTrash />
                </button>
              </div>
              <div className="text-[11px] text-gray-600 mt-1 pl-6 flex items-center gap-1.5 whitespace-nowrap min-w-0">
                <span className="w-[72px] truncate" title={g.number ?? ""}>{g.number || "—"}</span>
                <span className="text-gray-300">·</span>
                <span className="w-[56px] truncate" title={g.owner ?? ""}>{g.owner || "—"}</span>
                <span className="ml-auto font-mono shrink-0">{g.created_at ? fmtDate(g.created_at) : ""}</span>
              </div>
            </div>
          );
        })}
        {groups.length === 0 && <div className="g-empty"><IconFolder /><span>暂无案例，点击「新建案例」</span></div>}
      </div>
    </div>
  );
}

/* ═══════════════════════ ③ 案例内容卡 ═══════════════════════ */
function CaseContent({
  group, displayFiles, images, search, statusFilter, tree, isUploading,
  selected, allPendingIds, analyzing,
  onSearch, onStatusFilter, onUpload, onToggleSelect, onToggleSelectAll, onAnalyze,
  onOpenFile, onEditCase, onRenameFile, onRenameAsset, onDeleteFile, onDeleteImage,
}: {
  group: VideoGroup | undefined;
  displayFiles: FileItem[];
  images: CaseAssetItem[];
  search: string;
  statusFilter: string;
  tree: TreeKey;
  isUploading: boolean;
  selected: Set<string>;
  allPendingIds: string[];
  analyzing: boolean;
  onSearch: (q: string) => void;
  onStatusFilter: (s: string) => void;
  onUpload: () => void;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: () => void;
  onAnalyze: () => void;
  onOpenFile: (f: FileItem, openParams: boolean, reparse?: boolean) => void;
  onEditCase: (g: VideoGroup) => void;
  onRenameFile: (id: string, name: string) => Promise<void>;
  onRenameAsset: (id: string, name: string) => Promise<void>;
  onDeleteFile: (f: FileItem) => void;
  onDeleteImage: (img: CaseAssetItem) => void;
}) {
  const [previewImg, setPreviewImg] = useState<CaseAssetItem | null>(null);
  /* ── 视图模式（网格/列表）与视频详情抽屉 ── */
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [detailFile, setDetailFile] = useState<FileItem | null>(null);

  /* ── 文件名/图片名 内联编辑（点铅笔直接在单元格编辑） ── */
  const [editing, setEditing] = useState<{ kind: "file" | "image"; id: string } | null>(null);
  const [editName, setEditName] = useState("");
  const committingRef = useRef(false);

  const startEdit = (kind: "file" | "image", id: string, name: string) => {
    setEditing({ kind, id });
    setEditName(name);
  };
  const cancelEdit = () => setEditing(null);
  const commitEdit = async () => {
    if (committingRef.current || !editing) return;
    committingRef.current = true;
    const { kind, id } = editing;
    const name = editName.trim();
    try {
      if (name) {
        if (kind === "file") await onRenameFile(id, name);
        else await onRenameAsset(id, name);
      }
    } catch { /* 父级已 alert */ }
    setEditing(null);
    committingRef.current = false;
  };
  /* 编辑态：输入框 + 固定后缀（后缀展示，不随重命名变化） */
  const editField = (ext: string) => (
    <span className="flex items-center gap-1 w-full">
      <input
        autoFocus
        value={editName}
        onChange={(e) => setEditName(e.target.value)}
        onBlur={() => void commitEdit()}
        onKeyDown={(e) => { if (e.key === "Enter") void commitEdit(); if (e.key === "Escape") cancelEdit(); }}
        className="flex-1 min-w-0 px-1.5 py-0.5 text-[13px] border border-[#4f7cff] rounded focus:outline-none"
      />
      {ext && <span className="shrink-0 text-gray-300 text-[12px] select-none">{ext}</span>}
    </span>
  );
  /* 文件名 → 主名(base) + 后缀(ext，取真实扩展名，展示用) */
  const splitName = (name: string, fileExt?: string | null) => {
    const ext = fileExt?.length ? fileExt : "";
    const base = ext && name.endsWith(ext) ? name.slice(0, -ext.length) : name;
    return { base, ext };
  };
  return (
    <div className="flex-1 min-w-0 case-card flex flex-col min-h-0">
      {/* 工具栏：案例名称(大加粗) + 编号/负责人 + 文件数 + 检索 | 状态筛选 + 上传 */}
      <div className="px-4 py-2.5 border-b-2 border-[#e4e9f2] flex items-center flex-wrap gap-x-3 gap-y-2 shrink-0">
        <div className="flex items-center gap-2.5 whitespace-nowrap min-w-0">
          <span className="text-[15px] font-bold text-gray-900 max-w-[220px] truncate" title={group?.name ?? ""}>{group?.name || "案例库"}</span>
          <span className="text-[12px] text-gray-600 font-medium w-[90px] truncate" title={group?.number ?? ""}>{group?.number || "—"}</span>
          <span className="text-[12px] text-gray-600 font-medium w-[70px] truncate" title={group?.owner ?? ""}>{group?.owner || "—"}</span>
          <span className="text-[11.5px] text-gray-500 shrink-0">{displayFiles.length} 个文件</span>
          {group && (
            <button className="p-1 rounded text-[#4f7cff] hover:bg-blue-50 transition-colors shrink-0" title="编辑案例"
              onClick={() => onEditCase(group)}>
              <IconPencil />
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap ml-auto">
          <input
            className="g-input !w-[168px] !h-[30px] !text-[12px]" placeholder="搜索名称 / 摘要 / 案件编号"
            value={search} onChange={(e) => onSearch(e.target.value)}
          />
          <select className="g-input !w-[110px] !h-[30px] !text-[12px]" value={statusFilter} onChange={(e) => onStatusFilter(e.target.value)}>
            <option value="all">全部状态</option>
            <option value="PRE_PROCESSING">预处理中</option>
            <option value="READY_FOR_ANALYSIS">待分析</option>
            <option value="ANALYZING">分析中</option>
            <option value="COMPLETED">已完成</option>
            <option value="FAILED">失败</option>
          </select>
          {/* 上传：白底 outline（与新建案例蓝色等大） */}
          <button className="g-btn" onClick={onUpload} disabled={isUploading}>
            <IconPlus />
            {isUploading ? "上传中..." : "上传"}
          </button>
          {/* 解析：未勾选 → 处理当前列表全部待处理；勾选后 → 批量解析勾选的 */}
          <button className="g-btn g-btn-primary" onClick={onAnalyze}
            disabled={analyzing || (selected.size === 0 && allPendingIds.length === 0)} title="选择解析模式并启动待处理视频（极速概览 / 标准检索）">
            <IconPlay2 />
            {selected.size > 0 ? `批量解析 (${selected.size})` : `解析 (${allPendingIds.length})`}
          </button>
          {/* 视图切换器：网格（高亮）/ 列表 */}
          <div className="fl-view-toggle">
            <button className={viewMode === "grid" ? "active" : ""} onClick={() => setViewMode("grid")} title="网格视图">
              <IconGrid />
            </button>
            <button className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")} title="列表视图">
              <IconList />
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {viewMode === "grid" ? (
          <div className="fl-grid">
            {/* ── 视频卡片 ── */}
            {displayFiles.map((f) => {
              const ps = inferProcessStatus(f);
              const sm = PROCESS_STATUS_META[ps];
              const mode = inferParseMode(f);
              const { base, ext } = splitName(f.name, f.file_ext);
              /* 解析中文案按模式区分：极速=生成摘要 / 标准=提取特征 */
              const statusLabel = ps === "ANALYZING"
                ? (mode === "quick" ? "解析中 · 生成摘要" : "解析中 · 提取特征")
                : sm.label;
              return (
                <div key={f.id} className="fl-card" onClick={() => setDetailFile(f)}>
                  <div className="fl-cover">
                    <div className="fl-cover-bg"><VideoIcon /></div>
                    <img className="fl-thumb" src={`/api/v1/videos/${f.id}/thumbnail/0`} alt="" loading="lazy"
                      onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0"; }} />
                    {f.duration != null && <span className="fl-dur">{fmtDuration(f.duration)}</span>}
                    <span className={"fl-status fl-status-" + sm.css}>
                      {sm.pulse && <span className="pulse" />}
                      {statusLabel}
                    </span>
                    {/* 完成态模式暗示角标：极速=文档图标 / 标准=搜索图标 */}
                    {ps === "COMPLETED" && (
                      <span className={"fl-mode-badge " + (mode === "quick" ? "quick" : "standard")}
                        title={mode === "quick" ? "极速概览模式" : "标准检索模式"}>
                        {mode === "quick" ? <IconDoc /> : <IconSearch />}
                      </span>
                    )}
                    <div className="fl-actions">
                      <button title={f.current_status === "completed" ? "查看结果" : "预览视频"}
                        onClick={(e) => { e.stopPropagation(); onOpenFile(f, false); }}>
                        <IconEye />
                      </button>
                      <button title="重命名文件"
                        onClick={(e) => { e.stopPropagation(); startEdit("file", f.id, base); }}>
                        <IconPencil />
                      </button>
                      <button title="删除文件"
                        onClick={(e) => { e.stopPropagation(); onDeleteFile(f); }}>
                        <IconTrash />
                      </button>
                    </div>
                  </div>
                  <div className="fl-info">
                    {editing?.kind === "file" && editing.id === f.id ? editField(ext) : (
                      <span className="fl-name" title={f.name}>
                        <span className="fl-name-base">{base}</span>
                        {ext && <span className="fl-ext">{ext}</span>}
                      </span>
                    )}
                    <span className="fl-size">{fmtBytes(f.file_size)}</span>
                  </div>
                </div>
              );
            })}
            {/* ── 图片卡片 ── */}
            {images.filter((img) => !search.trim() || img.name.toLowerCase().includes(search.trim().toLowerCase())).map((img) => {
              const { base, ext } = splitName(img.name, img.file_ext);
              return (
                <div key={img.id} className="fl-card"
                  onClick={() => { if (tree.startsWith("g:")) setPreviewImg(img); }}>
                  <div className="fl-cover">
                    <div className="fl-cover-bg"><ImageIcon /></div>
                    {group && (
                      <img className="fl-thumb fl-thumb-contain" src={api.getAssetFileUrl(group.groupId, img.id)} alt="" loading="lazy"
                        onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0"; }} />
                    )}
                    <span className="fl-status fl-status-image">图片</span>
                    <div className="fl-actions">
                      {tree.startsWith("g:") && (
                        <button title="预览图片" onClick={(e) => { e.stopPropagation(); setPreviewImg(img); }}>
                          <IconEye />
                        </button>
                      )}
                      <button title="重命名图片" onClick={(e) => { e.stopPropagation(); startEdit("image", img.id, base); }}>
                        <IconPencil />
                      </button>
                      <button title="删除图片" onClick={(e) => { e.stopPropagation(); onDeleteImage(img); }}>
                        <IconTrash />
                      </button>
                    </div>
                  </div>
                  <div className="fl-info">
                    {editing?.kind === "image" && editing.id === img.id ? editField(ext) : (
                      <span className="fl-name" title={img.name}>
                        <span className="fl-name-base">{base}</span>
                        {ext && <span className="fl-ext">{ext}</span>}
                      </span>
                    )}
                    <span className="fl-size">{fmtBytes(img.file_size)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
        <table className="g-table">
          <thead>
            <tr>
              <th className="w-10">
                <input type="checkbox" className="cursor-pointer" title="全选待处理"
                  checked={allPendingIds.length > 0 && allPendingIds.every((id) => selected.has(id))}
                  disabled={allPendingIds.length === 0} onChange={onToggleSelectAll} />
              </th>
              <th className="w-10">类型</th>
              <th className="w-[240px]">文件名</th>
              <th className="w-24">大小</th>
              <th className="w-24">时长</th>
              <th className="w-36">上传时间</th>
              <th className="w-28">状态</th>
              <th className="w-[220px] text-right pr-4">操作</th>
            </tr>
          </thead>
          <tbody>
            {displayFiles.map((f) => {
              const ps = inferProcessStatus(f);
              const sm = PROCESS_STATUS_META[ps];
              const mode = inferParseMode(f);
              /* 解析中文案按模式区分：极速=生成摘要 / 标准=提取特征 */
              const statusLabel = ps === "ANALYZING"
                ? (mode === "quick" ? "解析中 · 生成摘要" : "解析中 · 提取特征")
                : sm.label;
              return (
                <tr key={f.id}>
                  <td>
                    <input type="checkbox" className="cursor-pointer" title={f.current_status === "pending" ? "勾选后批量解析" : "仅待处理可批量解析"}
                      checked={selected.has(f.id)}
                      disabled={f.current_status !== "pending"}
                      onChange={() => onToggleSelect(f.id)} />
                  </td>
                  <td><span className="inline-flex items-center justify-center w-6 h-6 rounded bg-gray-50 text-gray-500"><VideoIcon /></span></td>
                  <td className="text-gray-900 font-medium" title={f.name}>
                    {(() => { const { base, ext } = splitName(f.name, f.file_ext); return (
                      editing?.kind === "file" && editing.id === f.id ? editField(ext) : (
                        <span className="flex items-center gap-1 w-full">
                          <span className="truncate flex-1">{base}</span>
                          {ext && <span className="shrink-0 text-gray-300 text-[12px] select-none">{ext}</span>}
                        </span>
                      )
                    ); })()}
                  </td>
                  <td className="text-gray-500">{fmtBytes(f.file_size)}</td>
                  <td className="text-gray-500">{f.duration != null ? fmtDuration(f.duration) : "-"}</td>
                  <td className="text-gray-500">{f.created_at ? fmtDate(f.created_at) : "-"}</td>
                  <td>
                    <span className={"g-badge " + sm.badge}>
                      {sm.pulse && <span className="pulse" />}
                      {statusLabel}
                      {ps === "COMPLETED" && (f.versions_count ?? 1) > 1 && (
                        <span className="opacity-80"> · 共 {f.versions_count} 版</span>
                      )}
                      {ps === "COMPLETED" && (
                        <span className={"fl-badge-sm " + mode} title={mode === "quick" ? "极速概览模式" : "标准检索模式"}>
                          {mode === "quick" ? "极速" : "标准"}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    <div className="inline-flex items-center gap-1.5">
                      {/* 四个操作：解析(闪电) → 预览/结果 → 重命名 → 删除（前三个灰、hover 变蓝；删除红） */}
                      <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors"
                        title={f.current_status === "completed" ? "重新分析（可切换极速 / 标准）" : "选择模式并启动分析"}
                        onClick={() => onOpenFile(f, true, f.current_status === "completed")}>
                        {f.current_status === "completed" ? <IconBoltSolid /> : <IconBolt />}
                      </button>
                      {/* 预览/查看结果合并为一个眼睛按钮：未处理=预览，已完成=查看结果 */}
                      <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors"
                        title={f.current_status === "completed" ? "查看结果" : "预览视频"}
                        onClick={() => onOpenFile(f, false)}>
                        <IconEye />
                      </button>
                      {/* 重命名文件：内联编辑 */}
                      <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors" title="重命名文件"
                        onClick={() => startEdit("file", f.id, splitName(f.name, f.file_ext).base)}>
                        <IconPencil />
                      </button>
                      <button className="p-1.5 rounded-md text-red-500 hover:text-red-600 hover:bg-red-50 transition-colors" title="删除文件"
                        onClick={() => onDeleteFile(f)}>
                        <IconTrash />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {/* 图片素材行 */}
            {images.filter((img) => !search.trim() || img.name.toLowerCase().includes(search.trim().toLowerCase())).map((img) => (
              <tr key={img.id}>
                <td />
                <td><span className="inline-flex items-center justify-center w-6 h-6 rounded bg-gray-50 text-gray-500">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path strokeLinecap="round" strokeLinejoin="round" d="M21 15l-5-5L5 21" /></svg>
                </span></td>
                <td className="text-gray-800 font-medium" title={img.name}>
                  {(() => { const { base, ext } = splitName(img.name, img.file_ext); return (
                    editing?.kind === "image" && editing.id === img.id ? editField(ext) : (
                      <span className="flex items-center gap-1 w-full">
                        <span className="truncate flex-1">{base}</span>
                        {ext && <span className="shrink-0 text-gray-300 text-[12px] select-none">{ext}</span>}
                        <button className="shrink-0 p-0.5 rounded text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors" title="重命名图片"
                          onClick={() => startEdit("image", img.id, base)}>
                          <IconPencil />
                        </button>
                      </span>
                    )
                  ); })()}
                </td>
                <td className="text-gray-500">{fmtBytes(img.file_size)}</td>
                <td className="text-gray-400">—</td>
                <td className="text-gray-500">{img.created_at ? fmtDate(img.created_at) : "-"}</td>
                <td><span className="g-badge wait">图片</span></td>
                <td className="text-right pr-4 whitespace-nowrap">
                  <div className="inline-flex items-center gap-1.5">
                    {tree.startsWith("g:") && (
                      <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors" title="预览图片"
                        onClick={() => setPreviewImg(img)}>
                        <IconEye />
                      </button>
                    )}
                    <button className="p-1.5 rounded-md text-red-500 hover:text-red-600 hover:bg-red-50 transition-colors" title="删除图片"
                      onClick={() => onDeleteImage(img)}>
                      <IconTrash />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
        {displayFiles.length === 0 && images.length === 0 && (
          <div className="g-empty">
            <IconFolder />
            <span>{search || statusFilter !== "all" ? "当前筛选下暂无文件" : "点击「上传」归档视频/图片到此案例"}</span>
          </div>
        )}
      </div>

      {/* 图片预览弹窗 */}
      {previewImg && group && (
        <div className="g-modal-overlay" onClick={() => setPreviewImg(null)}>
          <div className="g-modal" style={{ maxWidth: "70vw" }} onClick={(e) => e.stopPropagation()}>
            <div className="g-card-hd">
              <span className="g-card-tt">{previewImg.name}</span>
              <button className="modal-x" onClick={() => setPreviewImg(null)} title="关闭" aria-label="关闭">×</button>
            </div>
            <div className="p-4 flex items-center justify-center bg-gray-50" style={{ minHeight: 320 }}>
              <img src={api.getAssetFileUrl(group.groupId, previewImg.id)} alt={previewImg.name}
                style={{ maxWidth: "100%", maxHeight: "62vh", objectFit: "contain" }} />
            </div>
          </div>
        </div>
      )}
      {/* 视频详情抽屉 */}
      {detailFile && (
        <FileDetailDrawer file={detailFile} onClose={() => setDetailFile(null)} onRename={onRenameFile} onOpenWorkbench={(f) => onOpenFile(f, false)} />
      )}
    </div>
  );
}

/* ═══════════════════════ ③.5 解析模式配置弹窗（双模式互斥大卡 + 识别项配置） ═══════════════════════ */
const RECOG_ITEMS: { key: keyof RecognitionToggles; label: string }[] = [
  { key: "face", label: "人脸识别" },
  { key: "plate", label: "车辆识别" },
  { key: "ocr", label: "文字识别" },
];
function ParseModeModal({
  open, defaultMode, onCancel, onConfirm,
}: {
  open: boolean;
  defaultMode: ParseMode;
  onCancel: () => void;
  onConfirm: (mode: ParseMode, toggles: RecognitionToggles) => void;
}) {
  const [mode, setMode] = useState<ParseMode>(defaultMode);
  const [toggles, setToggles] = useState<RecognitionToggles>(ALL_TOGGLES);
  useEffect(() => {
    if (open) {
      setMode(defaultMode);
      setToggles(ALL_TOGGLES);
    }
  }, [open, defaultMode]);
  const selectMode = (m: ParseMode) => {
    setMode(m);
    /* 切换回极速概览 → 识别项恢复默认全开，与「仅生成文本摘要」定位保持一致 */
    if (m === "quick") setToggles(ALL_TOGGLES);
  };
  const toggleRecog = (k: keyof RecognitionToggles) => {
    if (mode !== "standard") return;
    setToggles((prev) => ({ ...prev, [k]: !prev[k] }));
  };
  if (!open) return null;
  const cfgDisabled = mode === "quick";
  return (
    <div className="g-modal-overlay" onClick={onCancel}>
      <div className="g-modal" style={{ width: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="g-card-hd">
          <span className="g-card-tt">启动智能分析 · 选择模式</span>
          <button className="g-btn g-btn-sm" onClick={onCancel}>×</button>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-[12px] text-gray-500">选择处理模式，决定算力消耗与产出内容（均可后续重新解析切换）</p>
          <div className="fl-mode-grid">
            <button className={"fl-mode-card quick" + (mode === "quick" ? " active" : "")}
              onClick={() => selectMode("quick")}>
              <span className="fl-mode-ic"><IconBoltSolid /></span>
              <span className="fl-mode-tt">极速概览模式</span>
              <span className="fl-mode-desc">仅生成文本摘要，低算力、极快出结果，适合快速浏览视频内容</span>
              <span className="fl-mode-tag">低算力·极快</span>
            </button>
            <button className={"fl-mode-card standard" + (mode === "standard" ? " active" : "")}
              onClick={() => selectMode("standard")}>
              <span className="fl-mode-ic"><IconSearch /></span>
              <span className="fl-mode-tt">标准检索模式</span>
              <span className="fl-mode-desc">提取人脸/车辆/文字结构化数据，支持研判检索，耗时较长</span>
              <span className="fl-mode-tag">中/高算力·较慢</span>
            </button>
          </div>
          {/* 识别项配置：极速置灰不可操作 / 标准可独立开关三项识别能力 */}
          <div className={"fl-mode-cfg" + (cfgDisabled ? " disabled" : "")}>
            <div className="fl-mode-cfg-tt">——— 识别项配置 ———</div>
            <div className="fl-mode-switches">
              {RECOG_ITEMS.map((item) => (
                <button key={item.key} type="button" disabled={cfgDisabled}
                  className={"fl-mode-switch" + (toggles[item.key] ? " on" : "")}
                  onClick={() => toggleRecog(item.key)}>
                  <span className="fl-switch-mark">{toggles[item.key] ? "☑" : "☐"}</span>
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button className="g-btn" onClick={onCancel}>取消</button>
            <button className="g-btn g-btn-primary" onClick={() => onConfirm(mode, toggles)}>确定</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ ④ 视频详情抽屉 ═══════════════════════ */
function FileDetailDrawer({
  file, onClose, onRename, onOpenWorkbench,
}: {
  file: FileItem;
  onClose: () => void;
  onRename: (id: string, name: string) => Promise<void>;
  onOpenWorkbench: (f: FileItem) => void;
}) {
  const hevcOk = useHEVCCapability();
  const [video, setVideo] = useState<VideoResponse | null>(null);
  const [meta, setMeta] = useState<VideoMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const commitRef = useRef(false);
  /* ── 两阶段处理流：解析模式（极速 / 标准）/ 启动中 / 实时实体 ── */
  const [modeOpen, setModeOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [parseMode, setParseMode] = useState<ParseMode>(() => inferParseMode(file));
  const [entities, setEntities] = useState<{ face?: number; plate?: number }>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setVideo(null);
    setMeta(null);
    Promise.all([
      api.getVideo(file.id).catch(() => null),
      api.fetchVideoMetadata(file.id).catch(() => null),
    ]).then(([v, m]) => {
      if (cancelled) return;
      setVideo(v as VideoResponse | null);
      setMeta(m as VideoMetadata | null);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [file.id]);

  const summary = video?.summary ?? null;
  const streamUrl = api.getVideoStreamUrl(file.id, hevcOk);
  const thumbUrl = `/api/v1/videos/${file.id}/thumbnail/0`;
  /* 标准检索模式统计条数据：优先读后端 analysis_entities，其次用实时轮询值兜底 */
  const entCounts = file.analysis_entities ?? null;
  const faceCount = entCounts?.face ?? entities.face ?? 0;
  const plateCount = entCounts?.plate ?? entities.plate ?? 0;
  const ocrCount = entCounts?.ocr ?? 0;
  const { base, ext } = (() => {
    const e = file.file_ext?.length ? file.file_ext : "";
    const b = e && file.name.endsWith(e) ? file.name.slice(0, -e.length) : file.name;
    return { base: b, ext: e };
  })();

  const resolution = (() => {
    const vs = meta?.video_streams?.[0];
    if (vs?.resolution) return vs.resolution;
    if (vs?.width && vs?.height) return `${vs.width}×${vs.height}`;
    return null;
  })();

  const startRename = () => { setNameDraft(base); setRenaming(true); };
  const commitRename = async () => {
    if (commitRef.current) return;
    commitRef.current = true;
    const name = nameDraft.trim();
    if (name) {
      try { await onRename(file.id, name); } catch { /* 父级已 alert */ }
    }
    commitRef.current = false;
    setRenaming(false);
  };

  const download = () => {
    const a = document.createElement("a");
    a.href = streamUrl;
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  /* ── 两阶段状态推断与精析进度 ── */
  const ps = inferProcessStatus(file);
  const progress = file.analysis_progress ?? file.current_progress ?? null;

  /* 分析中：轮询实时发现的实体数量（人脸 / 车牌） */
  useEffect(() => {
    if (ps !== "ANALYZING") { setEntities({}); return; }
    let cancelled = false;
    const poll = async () => {
      const [face, plate] = await Promise.all([
        api.fetchFaceData(file.id).then((d) => d?.identities?.length ?? 0).catch(() => null),
        api.fetchPlateData(file.id).then((d) => d?.detections?.length ?? 0).catch(() => null),
      ]);
      if (!cancelled) setEntities({ face: face ?? undefined, plate: plate ?? undefined });
    };
    poll();
    const iv = setInterval(poll, 6000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [ps, file.id]);

  /* 启动 / 重新 智能分析：按所选模式+识别项开关构造阶段二参数（极速=仅摘要 / 标准=按开关） */
  const runAnalysis = async (mode: ParseMode, toggles: RecognitionToggles) => {
    setStarting(true);
    try {
      const params = buildParamsByMode(mode, toggles, video);
      if (ps === "COMPLETED") await api.reanalyze(file.id, params);
      else await api.analyzeBatch([file.id], params);
      setParseMode(mode);
      setModeOpen(false);
      onClose();
    } catch (err) {
      alert(err instanceof Error ? err.message : "启动分析失败");
    } finally {
      setStarting(false);
    }
  };

  /* 失败重试：再次弹出模式配置，可降级（标准→极速）或升级（极速→标准） */
  const retry = () => {
    setParseMode(inferParseMode(file));
    setModeOpen(true);
  };

  /* 导出结构化数据（JSON） */
  const exportStructured = () => {
    const data = {
      file_name: file.name,
      video_id: file.id,
      duration: file.duration,
      file_size: file.file_size,
      resolution: resolution || null,
      codec: video?.video_codec ?? null,
      process_status: ps,
      algorithms: {
        face: video?.face_enabled ?? false,
        plate: video?.plate_enabled ?? false,
        ocr: video?.ocr_enabled ?? false,
        detection: video?.detection_enabled ?? false,
      },
      summary: summary ? {
        one_liner: summary.one_liner,
        main_topics: summary.main_topics,
        main_entities: summary.main_entities,
        tags: summary.tags,
      } : null,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${base}_结构化数据.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fl-drawer-overlay" onClick={onClose}>
      <div className="fl-drawer" onClick={(e) => e.stopPropagation()}>
        {/* 头部：文件名 + 重命名 + 关闭 */}
        <div className="fl-drawer-hd">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            {renaming ? (
              <input autoFocus value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={() => void commitRename()}
                onKeyDown={(e) => { if (e.key === "Enter") void commitRename(); if (e.key === "Escape") setRenaming(false); }}
                className="flex-1 min-w-0 px-2 py-1 text-[14px] border border-[#4f7cff] rounded focus:outline-none" />
            ) : (
              <span className="text-[14px] font-semibold text-gray-900 truncate" title={file.name}>{base}{ext}</span>
            )}
            {!renaming && (
              <button className="p-1 rounded text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors shrink-0" title="重命名" onClick={startRename}>
                <IconPencil />
              </button>
            )}
          </div>
          <button className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors shrink-0" title="关闭" onClick={onClose}>
            <IconClose />
          </button>
        </div>

        <div className="fl-drawer-body">
          {/* 视频播放器 */}
          <div className="fl-player">
            <video controls src={streamUrl} poster={thumbUrl} className="w-full h-full" />
          </div>

          {/* 智能识别结果 */}
          <div className="fl-section">
            <div className="fl-section-title"><IconSummary /><span>智能识别结果</span></div>
            {/* 两阶段处理流：预处理 / 精析进度 + 实时实体（按解析模式区分文案） */}
            {(ps === "PRE_PROCESSING" || ps === "ANALYZING") && (
              <div className="fl-progress-block">
                <div className="fl-progress-row">
                  <span className="fl-progress-label">
                    {ps === "PRE_PROCESSING"
                      ? "入库预处理中（转码 / 摘要）"
                      : parseMode === "quick" ? "极速概览 · 生成摘要中" : "标准检索 · 提取特征中"}
                  </span>
                  <span className="fl-progress-pct">{progress != null ? `${progress}%` : "…"}</span>
                </div>
                <div className="fl-progress-bar"><div className="fl-progress-fill" style={{ width: `${progress ?? 0}%` }} /></div>
                {ps === "ANALYZING" && parseMode === "standard" && (
                  <div className="fl-entities">
                    {entities.face != null || entities.plate != null
                      ? <>已发现{entities.face != null ? ` 人脸 ${entities.face}` : ""}{entities.plate != null ? ` · 车牌 ${entities.plate}` : ""}</>
                      : "正在提取人 / 车 / 文字…"}
                  </div>
                )}
              </div>
            )}
            {ps === "FAILED" && (
              <div className="fl-fail">
                <p className="fl-fail-tt"><IconError />解析失败</p>
                <p className="fl-fail-msg">{video?.error_message || "未知原因，请联系管理员检查服务日志。"}</p>
                <p className="fl-fail-tip">可点击「重新解析」更换模式重试，或删除该文件后重新上传。</p>
              </div>
            )}
            {loading ? (
              <div className="text-[12px] text-gray-400 py-3">加载中…</div>
            ) : summary ? (
              <>
                {summary.one_liner && (
                  <p className={parseMode === "quick" ? "fl-summary-text fl-summary-quick" : "fl-summary-text fl-summary-clamp"}>{summary.one_liner}</p>
                )}
                {(summary.main_topics.length > 0 || summary.main_entities.length > 0) && (
                  <div className="fl-summary-kv">
                    {summary.main_topics.length > 0 && (
                      <div className="fl-kv"><span className="fl-kv-k">主题</span><span className="fl-kv-v">{summary.main_topics.join("、")}</span></div>
                    )}
                    {summary.main_entities.length > 0 && (
                      <div className="fl-kv"><span className="fl-kv-k">主体</span><span className="fl-kv-v">{summary.main_entities.join("、")}</span></div>
                    )}
                  </div>
                )}
                {summary.tags.length > 0 && (
                  <div className="fl-tags">
                    {summary.tags.map((t, i) => <span key={t} className={"fl-tag fl-tag-" + (i % 4)}>#{t}</span>)}
                  </div>
                )}
                {/* 标准检索模式：人 / 车 / 文字统计条 → 点击跳转全屏研判页 */}
                {parseMode === "standard" && ps === "COMPLETED" && (
                  <div className="fl-stats">
                    <button className="fl-stat" onClick={() => onOpenWorkbench(file)}><IconPerson /><span>人员</span><b>{faceCount}</b></button>
                    <button className="fl-stat" onClick={() => onOpenWorkbench(file)}><IconCar /><span>车辆</span><b>{plateCount}</b></button>
                    <button className="fl-stat" onClick={() => onOpenWorkbench(file)}><IconText /><span>文字</span><b>{ocrCount}</b></button>
                  </div>
                )}
              </>
            ) : (
              <div className="text-[12px] text-gray-400 py-3">暂无摘要（视频处理完成后自动生成）</div>
            )}
          </div>

          {/* 基础元数据 */}
          <div className="fl-section">
            <div className="fl-section-title"><IconInfo /><span>基本信息</span></div>
            <div className="fl-meta">
              <div className="fl-meta-row"><span className="fl-meta-k">上传时间</span><span className="fl-meta-v">{file.created_at ? fmtDate(file.created_at) : "—"}</span></div>
              <div className="fl-meta-row"><span className="fl-meta-k">分辨率</span><span className="fl-meta-v">{resolution || "—"}</span></div>
              <div className="fl-meta-row"><span className="fl-meta-k">时长</span><span className="fl-meta-v">{file.duration != null ? fmtDuration(file.duration) : "—"}</span></div>
              <div className="fl-meta-row"><span className="fl-meta-k">文件大小</span><span className="fl-meta-v">{fmtBytes(file.file_size)}</span></div>
              <div className="fl-meta-row"><span className="fl-meta-k">编码</span><span className="fl-meta-v">{video?.video_codec || "—"}</span></div>
              <div className="fl-meta-row"><span className="fl-meta-k">MD5</span><span className="fl-meta-v fl-mono">{extractMd5(meta) ?? "—"}</span></div>
            </div>
          </div>
        </div>

        <div className="fl-drawer-ft">
          <button className="g-btn" onClick={startRename}><IconPencil />编辑</button>
          <button className="g-btn" onClick={download}><IconDownload />下载</button>
          <span className="flex-1" />
          {/* ── 根据两阶段状态动态渲染主按钮 ── */}
          {ps === "READY_FOR_ANALYSIS" && (
            <button className="g-btn g-btn-primary" onClick={() => setModeOpen(true)} disabled={starting}>
              <IconBolt />启动智能分析
            </button>
          )}
          {ps === "PRE_PROCESSING" && (
            <button className="g-btn g-btn-primary" disabled title="预处理完成后即可启动分析">预处理中…</button>
          )}
          {ps === "ANALYZING" && (
            <button className="g-btn g-btn-primary" disabled title="分析进行中，请查看下方实时结果">
              分析进行中… {progress != null ? `${progress}%` : ""}
            </button>
          )}
          {ps === "COMPLETED" && (
            <>
              <button className="g-btn" onClick={exportStructured}><IconDownload />导出结构化数据</button>
              <button className="g-btn g-btn-primary" onClick={() => { setParseMode(inferParseMode(file)); setModeOpen(true); }}><IconBoltSolid />重新分析</button>
            </>
          )}
          {ps === "FAILED" && (
            <button className="g-btn g-btn-primary" onClick={retry} disabled={starting}><IconRetry />重新解析</button>
          )}
        </div>
      </div>

      {/* 解析模式配置弹窗（极速概览 / 标准检索 + 识别项配置）——可升降级重选 */}
      <ParseModeModal
        open={modeOpen}
        defaultMode={parseMode}
        onCancel={() => setModeOpen(false)}
        onConfirm={runAnalysis}
      />
    </div>
  );
}

/* ═══════════════════════ 页面编排 ═══════════════════════ */
export function FileLibrary() {
  const { openWorkbench, uploadFiles, isUploading, refreshCaseGroups } = useApp();
  const [files, setFiles] = useState<FileItem[]>([]);
  const [groups, setGroups] = useState<VideoGroup[]>([]);
  const [images, setImages] = useState<CaseAssetItem[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [tree, setTree] = useState<TreeKey>("all");
  const [showNewGroup, setShowNewGroup] = useState(false);
  const [form, setForm] = useState({ name: "", number: "", owner: "" });
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [analyzing, setAnalyzing] = useState(false);
  const [modeTargets, setModeTargets] = useState<string[] | null>(null);
  const [pendingMode, setPendingMode] = useState<ParseMode>("quick");
  /* 案例编辑 */
  const [editCase, setEditCase] = useState<VideoGroup | null>(null);
  const [editForm, setEditForm] = useState({ name: "", number: "", owner: "" });
  const [savingEdit, setSavingEdit] = useState(false);

  const load = () => {
    api.listFiles().then((data) => setFiles(data ?? [])).catch(() => {});
    api.listGroups().then((data) => setGroups(data ?? [])).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
  }, []);

  /* 选中案例 → 拉取该案例图片素材 */
  useEffect(() => {
    setImages([]);
    if (!tree.startsWith("g:")) return;
    let cancelled = false;
    api.getGroupAssets(tree.slice(2)).then((d) => {
      if (!cancelled) setImages(d?.images ?? []);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [tree]);

  /* 切换视图（全部/未分组/案例）→ 清空勾选，避免跨范围误批量 */
  useEffect(() => { setSelected(new Set()); }, [tree]);

  const handleUploadFiles = () => {
    if (!tree.startsWith("g:")) { alert("请先选择案例"); return; }
    const gid = tree.slice(2);
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm,image/*";
    input.multiple = true;
    input.onchange = async () => {
      const files = Array.from(input.files ?? []);
      if (!files.length) return;
      const vids = files.filter((f) => /\.(mp4|mov|avi|mkv|webm)$/i.test(f.name) || f.type.startsWith("video/"));
      const imgs = files.filter((f) => f.type.startsWith("image/"));
      const uploadedIds: string[] = [];
      if (vids.length) uploadedIds.push(...(await uploadFiles(vids, gid, { stay: true })));
      if (imgs.length) {
        try { await api.uploadGroupAssets(gid, imgs); } catch (err) { alert(err instanceof Error ? err.message : "图片上传失败"); }
      }
      try {
        const d = await api.getGroupAssets(gid);
        setImages(d?.images ?? []);
      } catch { /* ignore */ }
      load();
      input.value = "";
      /* 上传视频成功后立即弹出解析模式配置弹窗（默认极速概览），便于直接启动分析 */
      if (uploadedIds.length) {
        setPendingMode("quick");
        setModeTargets(uploadedIds);
      }
    };
    input.click();
  };

  /* 新建案例：自动填充当日递增编号（可手动改） */
  const openNewCase = () => {
    setForm((prev) => ({ ...prev, number: genCaseNumber(groups) }));
    setShowNewGroup(true);
  };

  const createGroup = async () => {
    if (!form.name.trim()) { alert("请填写案例名称"); return; }
    setCreatingGroup(true);
    try {
      const g = await api.createGroup({ name: form.name.trim(), number: form.number.trim() || undefined, owner: form.owner.trim() || undefined });
      setShowNewGroup(false);
      setForm({ name: "", number: "", owner: "" });
      setTree(`g:${g.groupId}`);
      load();
      refreshCaseGroups();
    } catch (err) { alert(err instanceof Error ? err.message : "创建失败"); }
    setCreatingGroup(false);
  };

  /* 编辑案例：弹窗改 名称/编号/负责人 */
  const openEditCase = (g: VideoGroup) => {
    setEditForm({ name: g.name ?? "", number: g.number ?? "", owner: g.owner ?? "" });
    setEditCase(g);
  };

  const saveEditCase = async () => {
    if (!editCase) return;
    if (!editForm.name.trim()) { alert("请填写案例名称"); return; }
    setSavingEdit(true);
    try {
      await api.updateGroup(editCase.groupId, {
        name: editForm.name.trim(),
        number: editForm.number.trim() || undefined,
        owner: editForm.owner.trim() || undefined,
      });
      setEditCase(null);
      load();
      refreshCaseGroups();
    } catch (err) { alert(err instanceof Error ? err.message : "保存失败"); }
    setSavingEdit(false);
  };

  /* 重命名文件 / 素材：单元格内联编辑提交 */
  const handleRenameFile = async (id: string, name: string) => {
    try { await api.renameFile(id, name); load(); }
    catch (err) { alert(err instanceof Error ? err.message : "重命名失败"); }
  };

  const handleRenameAsset = async (id: string, name: string) => {
    const gid = tree.startsWith("g:") ? tree.slice(2) : null;
    if (!gid) return;
    try { await api.renameGroupAsset(gid, id, name); load(); }
    catch (err) { alert(err instanceof Error ? err.message : "重命名失败"); }
  };

  const deleteCase = async (g: VideoGroup) => {
    if (!window.confirm(`确认删除案例「${g.name}」？将删除其下全部视频与图片，不可恢复。`)) return;
    try {
      await api.deleteGroup(g.groupId);
      if (tree === `g:${g.groupId}`) setTree("all");
      load();
      refreshCaseGroups();
    } catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };

  const deleteFile = async (f: FileItem) => {
    if (!window.confirm(`确认删除「${f.name}」？将删除该文件全部解析版本并释放磁盘空间。`)) return;
    try { await api.deleteFile(f.id); load(); }
    catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };

  const deleteImage = async (img: CaseAssetItem) => {
    if (!window.confirm(`确认删除图片「${img.name}」？`)) return;
    try {
      await api.deleteGroupAsset(tree.slice(2), img.id);
      setImages((prev) => prev.filter((x) => x.id !== img.id));
    } catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };

  /* 树选中失效（组被删）→ 回退第一个案例 */
  useEffect(() => {
    if (groups.length && !groups.some((g) => tree === `g:${g.groupId}`)) {
      setTree(`g:${groups[0].groupId}`);
    }
  }, [groups, tree]);

  const treeFiltered = useMemo(() => {
    if (tree === "all") return files;
    if (tree === "ungrouped") return files.filter((f) => !f.group_id);
    const gid = tree.slice(2);
    return files.filter((f) => f.group_id === gid);
  }, [tree, files]);

  const displayFiles = useMemo(() => {
    let list = treeFiltered;
    if (statusFilter !== "all") list = list.filter((f) => inferProcessStatus(f) === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((f) => {
        // 视频名称匹配
        if (f.name.toLowerCase().includes(q)) return true;
        // 视频摘要内容匹配（如搜"红色轿车"命中摘要描述）
        if (f.current_summary?.one_liner?.toLowerCase().includes(q)) return true;
        // 案件编号匹配
        const g = groups.find((gg) => gg.groupId === f.group_id);
        if (g?.number?.toLowerCase().includes(q)) return true;
        return false;
      });
    }
    return list;
  }, [treeFiltered, statusFilter, search, groups]);

  const selectedGroup = groups.find((g) => tree === `g:${g.groupId}`);

  /* ── 批量解析：勾选（仅待处理可勾）或当前列表全部待处理 ── */
  const displayPendingIds = useMemo(
    () => displayFiles.filter((f) => f.current_status === "pending").map((f) => f.id),
    [displayFiles],
  );

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      const allOn = displayPendingIds.every((id) => next.has(id));
      if (allOn) displayPendingIds.forEach((id) => next.delete(id));
      else displayPendingIds.forEach((id) => next.add(id));
      return next;
    });
  }, [displayPendingIds]);

  /* 点「解析」按钮 → 弹出模式配置（极速概览 / 标准检索），确认后整批启动 */
  const handleAnalyze = () => {
    const targets = selected.size > 0 ? Array.from(selected) : displayPendingIds;
    if (targets.length === 0) return;
    setPendingMode("quick");
    setModeTargets(targets);
  };

  const handleModeConfirm = async (mode: ParseMode, toggles: RecognitionToggles) => {
    if (!modeTargets) return;
    setAnalyzing(true);
    try {
      await api.analyzeBatch(modeTargets, buildParamsByMode(mode, toggles));
      setSelected(new Set());
      setModeTargets(null);
      load();  // 提交结果靠列表刷新 + 侧栏徽章自然反馈，不弹原生窗
    } catch (err) {
      alert(err instanceof Error ? err.message : "批量解析失败");
      setModeTargets(null);
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="h-full flex flex-col gap-2 p-2">
      {/* ① 顶部卡 */}
      <CaseHeader onNewCase={openNewCase} />

      {/* ② 左卡 + ③ 右卡 */}
      <div className="flex flex-1 gap-2 min-h-0">
        <CaseList
          groups={groups} files={files} tree={tree}
          onSelect={(gid) => setTree(`g:${gid}`)}
          onDeleteCase={deleteCase}
        />
        <CaseContent
          group={selectedGroup} displayFiles={displayFiles} images={images}
          search={search} statusFilter={statusFilter} tree={tree} isUploading={isUploading}
          selected={selected} allPendingIds={displayPendingIds} analyzing={analyzing}
          onSearch={setSearch} onStatusFilter={setStatusFilter} onUpload={handleUploadFiles}
          onToggleSelect={toggleSelect} onToggleSelectAll={toggleSelectAll} onAnalyze={handleAnalyze}
          onOpenFile={(f, openParams, reparse) => openWorkbench(f.id, { openParams, reparse })}
          onEditCase={openEditCase}
          onRenameFile={handleRenameFile}
          onRenameAsset={handleRenameAsset}
          onDeleteFile={deleteFile} onDeleteImage={deleteImage}
        />
      </div>

      {/* 新建案例弹窗 */}
      {showNewGroup && (
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ width: 440 }}>
            <div className="g-card-hd">
              <span className="g-card-tt">新建案例</span>
              <button className="modal-x" onClick={() => setShowNewGroup(false)} title="关闭" aria-label="关闭">×</button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="g-label">案例名称 <span style={{ color: "#ef4444" }}>*</span></label>
                <input className="g-input w-full" placeholder="如：2024-甲区抢劫案" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <label className="g-label">案例编号</label>
                <input className="g-input w-full" placeholder="如：A-2026-0814-01" value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} />
              </div>
              <div>
                <label className="g-label">负责人</label>
                <input className="g-input w-full" placeholder="如：张建国" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} />
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button className="g-btn" onClick={() => setShowNewGroup(false)}>取消</button>
                <button className="g-btn g-btn-primary" onClick={createGroup} disabled={creatingGroup}>
                  {creatingGroup ? "创建中…" : "创建案例"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 编辑案例弹窗：改 名称/编号/负责人 */}
      {editCase && (
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ width: 440 }}>
            <div className="g-card-hd">
              <span className="g-card-tt">编辑案例</span>
              <button className="modal-x" onClick={() => setEditCase(null)} title="关闭" aria-label="关闭">×</button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="g-label">案例名称 <span style={{ color: "#ef4444" }}>*</span></label>
                <input className="g-input w-full" placeholder="如：2024-甲区抢劫案" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
              </div>
              <div>
                <label className="g-label">案例编号</label>
                <input className="g-input w-full" placeholder="如：A-2026-0814-01" value={editForm.number} onChange={(e) => setEditForm({ ...editForm, number: e.target.value })} />
              </div>
              <div>
                <label className="g-label">负责人</label>
                <input className="g-input w-full" placeholder="如：张建国" value={editForm.owner} onChange={(e) => setEditForm({ ...editForm, owner: e.target.value })} />
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button className="g-btn" onClick={() => setEditCase(null)}>取消</button>
                <button className="g-btn g-btn-primary" onClick={saveEditCase} disabled={savingEdit}>
                  {savingEdit ? "保存中…" : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 批量解析 / 上传后：模式配置弹窗（极速概览 / 标准检索 + 识别项配置） */}
      <ParseModeModal
        open={!!modeTargets}
        defaultMode={pendingMode}
        onCancel={() => setModeTargets(null)}
        onConfirm={handleModeConfirm}
      />
    </div>
  );
}
