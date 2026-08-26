/* ════════════════════════════════════════════════════════════
   FileLibrary — 案例库（v0.34 三卡片布局）
   拆成 3 个组件（中间留间隙、全圆角）：
     ① CaseHeader  顶部卡：案例库标题 + 新建案例
     ② CaseList    左卡：案例列表（编号/负责人/时间/文件数 + 删除）
     ③ CaseContent 右卡：案例内容（文件表格：视频 + 图片 + 上传 + 状态筛选）
   数据源 = /files + /groups + /groups/{id}/assets
   ════════════════════════════════════════════════════════════ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../services/api";
import { useApp } from "../AppContext";
import type { FileItem, VideoGroup, CaseAssetItem, PipelineParams, VideoResponse, VideoMetadata } from "../types";
import { fmtDuration, fmtDate, fmtBytes } from "../utils/helpers";
import { IconFolder, IconPlus, IconPlay2, IconTrash, IconPencil, IconBolt, IconBoltSolid, IconEye, IconGrid, IconList, IconDownload, IconClose, IconInfo, IconRetry } from "./icons";
import { useHEVCCapability } from "../hooks/useHEVCCapability";
import { useDisableVideoInteraction } from "../hooks/useDisableVideoInteraction";
import { SmartSuggestDialog } from "./SmartSuggestDialog";

type TreeKey = "all" | "ungrouped" | `g:${string}`;

const STATUS_META: Record<string, { label: string; cls: string; badge: string; pulse?: boolean }> = {
  pending: { label: "待处理", cls: "pre", badge: "wait", pulse: true },
  queued: { label: "排队中", cls: "queued", badge: "warn", pulse: true },
  processing: { label: "处理中", cls: "analyzing", badge: "run", pulse: true },
  completed: { label: "已完成", cls: "completed", badge: "ok" },
  failed: { label: "失败", cls: "failed", badge: "err" },
  image: { label: "图片", cls: "image", badge: "image" },
};
function statusOf(f: FileItem): { cls: string; badge: string; pulse?: boolean; label: string } {
  if (f.current_status === "pending" && f.queued) return STATUS_META.queued;
  const st = f.current_status ?? "pending";
  return STATUS_META[st] ?? STATUS_META.pending;
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
  onSearch, onStatusFilter, onUpload, onUploadFolder, onToggleSelect, onToggleSelectAll, onAnalyze,
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
  onUploadFolder: () => void;
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
  /* ── 添加下拉：合并「选择视频文件 / 上传文件夹」 ── */
  const [addOpen, setAddOpen] = useState(false);

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
          {/* 视图切换器：网格 / 列表 —— 放最左 */}
          <div className="fl-view-toggle">
            <button className={viewMode === "grid" ? "active" : ""} onClick={() => setViewMode("grid")} title="网格视图">
              <IconGrid />
            </button>
            <button className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")} title="列表视图">
              <IconList />
            </button>
          </div>
          <input
            className="g-input !w-[168px] !h-[30px] !text-[12px]" placeholder="搜索名称 / 摘要 / 案件编号"
            value={search} onChange={(e) => onSearch(e.target.value)}
          />
          <select className="g-input !w-[110px] !h-[30px] !text-[12px]" value={statusFilter} onChange={(e) => onStatusFilter(e.target.value)}>
            <option value="all">全部状态</option>
            <option value="pending">待处理</option>
            <option value="queued">排队中</option>
            <option value="processing">处理中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
          </select>
          {/* 添加：合并「选择视频文件 / 上传文件夹」一键下拉（自动识别并上传） */}
          <div className="relative">
            <button className="g-btn" onClick={() => setAddOpen((o) => !o)} disabled={isUploading}>
              <IconPlus />
              {isUploading ? "上传中..." : "添加"}
            </button>
            {addOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setAddOpen(false)} />
                <div className="absolute top-full right-0 mt-1 bg-white rounded-lg shadow-xl border border-gray-200 z-20 overflow-hidden min-w-[160px] py-0.5">
                  <button
                    className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 text-gray-700"
                    onClick={() => { setAddOpen(false); onUpload(); }}
                    title="选择视频文件上传到当前案例"
                  >
                    <VideoIcon />
                    选择视频文件
                  </button>
                  <button
                    className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 text-gray-700"
                    onClick={() => { setAddOpen(false); onUploadFolder(); }}
                    title="上传整个文件夹（含子文件夹内的视频，扁平归档到本案例）"
                  >
                    <span className="[&_svg]:w-3.5 [&_svg]:h-3.5"><IconFolder /></span>
                    上传文件夹
                  </button>
                </div>
              </>
            )}
          </div>
          {/* 解析：未勾选 → 处理当前列表全部待处理；勾选后 → 批量解析勾选的 */}
          <button className="g-btn g-btn-primary" onClick={onAnalyze}
            disabled={analyzing || (selected.size === 0 && allPendingIds.length === 0)} title="打开参数面板并启动待处理视频">
            <IconPlay2 />
            {selected.size > 0 ? `批量解析 (${selected.size})` : `解析 (${allPendingIds.length})`}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {viewMode === "grid" ? (
          <div className="fl-grid">
            {/* ── 视频卡片 ── */}
            {displayFiles.map((f) => {
              const sm = statusOf(f);
              const { base, ext } = splitName(f.name, f.file_ext);
              const statusLabel = sm.label;
              return (
                <div key={f.id} className="fl-card" onClick={() => setDetailFile(f)}>
                  <div className="fl-cover">
                    <div className="fl-cover-bg"><VideoIcon /></div>
                    <img className="fl-thumb" src={`/api/v1/videos/${f.id}/thumbnail/0`} alt="" loading="lazy"
                      onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0"; }} />
                    {f.duration != null && <span className="fl-dur">{fmtDuration(f.duration)}</span>}
                    <span className={"fl-status fl-status-" + sm.cls}>
                      {sm.pulse && <span className="pulse" />}
                      {statusLabel}
                    </span>
                    <div className="fl-card-actions-sm">
                      {/* 统一 3 操作（v0.37）：查看 | 编辑 | 删除；视觉从右到左依次为 删除 / 编辑 / 查看 */}
                      <button className="fl-card-action-sm" title="查看（跳转到视频解析页面，不自动打开参数设置）"
                        onClick={(e) => { e.stopPropagation(); onOpenFile(f, false); }}>
                        <IconEye />
                      </button>
                      <button className="fl-card-action-sm" title="重命名" onClick={(e) => { e.stopPropagation(); startEdit("file", f.id, base); }}>
                        <IconPencil />
                      </button>
                      <button className="fl-card-action-sm fl-card-action-sm-danger" title="删除" onClick={(e) => { e.stopPropagation(); onDeleteFile(f); }}>
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
                  <input type="checkbox" className="fl-checkbox" title={f.current_status === "pending" ? "勾选后批量解析" : "仅待处理可批量解析"}
                    checked={selected.has(f.id)}
                    disabled={f.current_status !== "pending"}
                    onChange={(e) => { e.stopPropagation(); onToggleSelect(f.id); }}
                    onClick={(e) => e.stopPropagation()} />
                </div>
              );
            })}
            {/* ── 图片卡片 ── */}
            {images.filter((img) => {
              // 状态过滤：图片状态时显示图片，其他状态时只在"全部状态"时显示
              if (statusFilter !== "all" && statusFilter !== "image") return false;
              // 搜索过滤
              return !search.trim() || img.name.toLowerCase().includes(search.trim().toLowerCase());
            }).map((img) => {
              const { base, ext } = splitName(img.name, img.file_ext);
              return (
                <div key={img.id} className="fl-card" onClick={() => setPreviewImg(img)}
                  draggable
                  onDragStart={(e) => {
                    /* v0.6 素材库扩充：携带案例素材信息，ImageLibrary 详情页可拖入 */
                    if (!group) return;
                    e.dataTransfer.setData("application/x-zhiying-asset", JSON.stringify({ groupId: group.groupId, assetId: img.id, name: img.name }));
                    e.dataTransfer.effectAllowed = "copy";
                  }}>
                  <div className="fl-cover">
                    <div className="fl-cover-bg"><ImageIcon /></div>
                    {group && (
                      <img className="fl-thumb fl-thumb-contain" src={api.getAssetFileUrl(group.groupId, img.id)} alt="" loading="lazy"
                        onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0"; }} />
                    )}
                    <span className="fl-status fl-status-image">图片</span>
                    <div className="fl-card-actions-sm">
                      <button className="fl-card-action-sm" title="重命名" onClick={(e) => { e.stopPropagation(); startEdit("image", img.id, base); }}>
                        <IconPencil />
                      </button>
                      <button className="fl-card-action-sm fl-card-action-sm-danger" title="删除" onClick={(e) => { e.stopPropagation(); onDeleteImage(img); }}>
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
              const sm = statusOf(f);
              const statusLabel = sm.label;
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
                      {f.current_status === "completed" && (f.versions_count ?? 1) > 1 && (
                        <span className="opacity-80"> · 共 {f.versions_count} 版</span>
                      )}
                    </span>
                  </td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    <div className="inline-flex items-center gap-1.5">
                      {/* 四个操作：解析(闪电) → 预览/结果 → 重命名 → 删除（前三个灰、hover 变蓝；删除红） */}
                      <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors"
                        title={f.current_status === "completed" ? "重新分析" : "打开参数面板并启动分析"}
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
            {images.filter((img) => {
              // 状态过滤：图片状态时显示图片，其他状态时只在"全部状态"时显示
              if (statusFilter !== "all" && statusFilter !== "image") return false;
              // 搜索过滤
              return !search.trim() || img.name.toLowerCase().includes(search.trim().toLowerCase());
            }).map((img) => (
              <tr key={img.id} draggable
                onDragStart={(e) => {
                  /* v0.6 素材库扩充：携带案例素材信息，ImageLibrary 详情页可拖入 */
                  if (!group) return;
                  e.dataTransfer.setData("application/x-zhiying-asset", JSON.stringify({ groupId: group.groupId, assetId: img.id, name: img.name }));
                  e.dataTransfer.effectAllowed = "copy";
                }}>
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
      {previewImg && group && createPortal(
        <div className="g-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setPreviewImg(null); }}>
          <div className="g-modal" style={{ maxWidth: "70vw" }}>
            <div className="g-card-hd">
              <span className="g-card-tt">{previewImg.name}</span>
              <button className="modal-x" onClick={() => setPreviewImg(null)} title="关闭" aria-label="关闭">×</button>
            </div>
            <div className="p-4 flex items-center justify-center bg-gray-50" style={{ minHeight: 320 }}>
              <img src={api.getAssetFileUrl(group.groupId, previewImg.id)} alt={previewImg.name}
                style={{ maxWidth: "100%", maxHeight: "62vh", objectFit: "contain" }} />
            </div>
          </div>
        </div>,
        document.body,
      )}
      {/* 视频详情抽屉 */}
      {detailFile && (
        <FileDetailDrawer file={detailFile} onClose={() => setDetailFile(null)} onRename={onRenameFile} onOpenWorkbench={(f) => onOpenFile(f, false)} onDeleteFile={onDeleteFile} />
      )}
    </div>
  );
}

/* ═══════════════════════ ④ 视频详情抽屉 ═══════════════════════ */
function FileDetailDrawer({
  file, onClose, onRename, onOpenWorkbench, onDeleteFile,
}: {
  file: FileItem;
  onClose: () => void;
  onRename: (id: string, name: string) => Promise<void>;
  onOpenWorkbench: (f: FileItem) => void;
  onDeleteFile?: (f: FileItem) => void;
}) {
  const hevcOk = useHEVCCapability();
  const [video, setVideo] = useState<VideoResponse | null>(null);
  const [meta, setMeta] = useState<VideoMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const commitRef = useRef(false);
  const [starting, setStarting] = useState(false);
  /* ── 「参数设置」小面板：6 个核心开关本地态（点击即保存，无 dirty/saving 状态） ── */
  const [toggles, setToggles] = useState<{
    detection_enabled: boolean; face_enabled: boolean; plate_enabled: boolean;
    ocr_enabled: boolean; search_index_enabled: boolean; summary_enabled: boolean;
  } | null>(null);

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

  /* ── 视频详情落定后初始化「参数设置」本地态：优先持久化的智能推荐，否则回退当前持久化字段
     每个 file.id 只初始化一次（save 后 video 更新不会触发重初始化，避免把用户改完的值又覆盖回 recommended）── */
  const initTogglesForFileRef = useRef<string | null>(null);
  useEffect(() => {
    if (!video) {
      setToggles(null);
      initTogglesForFileRef.current = null;
      return;
    }
    if (initTogglesForFileRef.current === file.id) return;
    const sp = video.suggested_params ?? null;
    setToggles({
      detection_enabled: sp?.detection_enabled ?? video.detection_enabled,
      face_enabled: sp?.face_enabled ?? video.face_enabled,
      plate_enabled: sp?.plate_enabled ?? video.plate_enabled,
      ocr_enabled: sp?.ocr_enabled ?? video.ocr_enabled,
      search_index_enabled: sp?.search_index_enabled ?? video.search_index_enabled,
      summary_enabled: sp?.summary_enabled ?? video.summary_enabled,
    });
    initTogglesForFileRef.current = file.id;
  }, [video, file.id]);

  const streamUrl = api.getVideoStreamUrl(file.id, hevcOk);
  const thumbUrl = `/api/v1/videos/${file.id}/thumbnail/0`;
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

  /* ── 「参数设置」小面板辅助 ── */
  async function persistToggles(next: NonNullable<typeof toggles>) {
    try {
      const updated = await api.updateToggles(file.id, next);
      setVideo(updated as VideoResponse);
    } catch (e) {
      alert(e instanceof Error ? e.message : "保存失败");
      /* 保存失败：刷新 video 把本地态重新对齐到服务端 */
      try {
        const fresh = await api.getVideo(file.id);
        if (fresh) setVideo(fresh as VideoResponse);
      } catch { /* ignore */ }
    }
  }

  function setToggle<K extends keyof NonNullable<typeof toggles>>(k: K, v: boolean) {
    setToggles((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [k]: v };
      // 链式：关闭 detection → 同步关闭 face / plate（与后端校验一致）
      if (k === "detection_enabled" && !v) {
        next.face_enabled = false;
        next.plate_enabled = false;
      }
      // 点击即保存（乐观更新 → 后端持久化）
      void persistToggles(next);
      return next;
    });
  }

  async function applySuggested() {
    const sp = video?.suggested_params;
    if (!sp) return;
    /* 智能推荐场景预设（SCENE_CLASSES）全部不开启摘要——这里同步把摘要关掉，
       保持「智能推荐 = 一键重置参数」语义，不让摘要保留用户之前勾选的状态 */
    const next = {
      detection_enabled: sp.detection_enabled ?? false,
      face_enabled: sp.face_enabled ?? false,
      plate_enabled: sp.plate_enabled ?? false,
      ocr_enabled: sp.ocr_enabled ?? false,
      search_index_enabled: sp.search_index_enabled ?? false,
      summary_enabled: false,
    };
    setToggles(next);
    await persistToggles(next);
  }

  /* ── 单状态机：后端 status（pending/processing/completed/failed）直接驱动 ── */
  const ps = file.current_status ?? "pending";
  const progress = file.current_progress ?? null;

  /* 直接启动解析：用「参数设置」本地态覆盖 video 中的开关字段
     ─ 本地 toggles 优先（即使 PATCH 还在 in-flight 也能用用户意图启动）
     ── reparse=false：pending 启动管道；reparse=true：completed/failed 建新版本 */
  async function handleAnalyze(reparse: boolean) {
    if (starting || !video) return;
    setStarting(true);
    try {
      const params: PipelineParams = {
        content_type: video.content_type,
        vision_enabled: video.vision_enabled,
        audio_enabled: video.audio_enabled,
        ocr_enabled: toggles?.ocr_enabled ?? video.ocr_enabled,
        caption_enabled: (toggles?.summary_enabled ?? video.summary_enabled) ? true : video.caption_enabled,
        detection_enabled: toggles?.detection_enabled ?? video.detection_enabled,
        detection_classes: video.detection_classes,
        face_enabled: toggles?.face_enabled ?? video.face_enabled,
        plate_enabled: toggles?.plate_enabled ?? video.plate_enabled,
        summary_enabled: toggles?.summary_enabled ?? video.summary_enabled,
        summary_mode: video.summary_mode,
        search_index_enabled: toggles?.search_index_enabled ?? video.search_index_enabled,
        language: video.language,
        sample_fps: video.sample_fps,
        segment_threshold: video.segment_threshold,
        caption_with_context: video.caption_with_context,
        summary_detail: video.summary_detail,
        encode_profile: video.encode_profile,
        apply_to_group: false,
      };
      await api.updateParams(file.id, params);
      onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : (reparse ? "重新分析失败" : "解析失败"));
    } finally {
      setStarting(false);
    }
  }

  /* 导出结构化数据（JSON） —— 已废弃（智能识别结果 section 删除后此导出无引用方），保留占位可后续扩展 */
  /* ── 已删除 exportStructured：原 export 按钮无调用方；如需重启请恢复下面代码并加按钮 ── */

  return createPortal(
    <div className="fl-drawer-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="fl-drawer">
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

          {/* 参数设置（v0.37）：智能推荐回填 + 6 开关（点击即保存）+ 智能推荐按钮 */}
          <div className="fl-section">
            <div className="fl-section-title">
              <IconBolt />
              <span>参数设置</span>
              {video?.suggested_scene_label && (
                <span
                  className="ml-auto inline-flex items-center gap-1 text-[11.5px] font-medium text-[#4f7cff] bg-[#eaf1ff] rounded px-2 py-0.5"
                  title={`基于 embedder 场景分类（${video.suggested_scene_label}，匹配度 ${((video.suggested_confidence ?? 0) * 100).toFixed(0)}%）自动回填`}
                >
                  <span className="fl-pulse-dot" />
                  智能推荐：{video.suggested_scene_label} {((video.suggested_confidence ?? 0) * 100).toFixed(0)}%
                </span>
              )}
            </div>
            {toggles ? (
              <>
                <div className="grid grid-cols-2 gap-1.5">
                  <label className="fl-alg !py-2">
                    <input
                      type="checkbox"
                      checked={toggles.detection_enabled}
                      onChange={(e) => setToggle("detection_enabled", e.target.checked)}
                    />
                    <span className="fl-alg-tt">物体检测</span>
                  </label>
                  <label className="fl-alg !py-2">
                    <input
                      type="checkbox"
                      checked={toggles.face_enabled}
                      onChange={(e) => setToggle("face_enabled", e.target.checked)}
                      disabled={!toggles.detection_enabled}
                      title={!toggles.detection_enabled ? "需先开启「物体检测」" : "SCRFD + ArcFace 人脸识别"}
                    />
                    <span className="fl-alg-tt">人脸</span>
                  </label>
                  <label className="fl-alg !py-2">
                    <input
                      type="checkbox"
                      checked={toggles.plate_enabled}
                      onChange={(e) => setToggle("plate_enabled", e.target.checked)}
                      disabled={!toggles.detection_enabled}
                      title={!toggles.detection_enabled ? "需先开启「物体检测」" : "HyperLPR3 车牌识别"}
                    />
                    <span className="fl-alg-tt">车牌</span>
                  </label>
                  <label className="fl-alg !py-2">
                    <input
                      type="checkbox"
                      checked={toggles.ocr_enabled}
                      onChange={(e) => setToggle("ocr_enabled", e.target.checked)}
                      title="RapidOCR PP-OCRv3 画面文字提取"
                    />
                    <span className="fl-alg-tt">OCR 文字</span>
                  </label>
                  <label className="fl-alg !py-2">
                    <input
                      type="checkbox"
                      checked={toggles.search_index_enabled}
                      onChange={(e) => setToggle("search_index_enabled", e.target.checked)}
                      title="搜索索引：4 编码路径 + 8 路召回"
                    />
                    <span className="fl-alg-tt">搜索索引</span>
                  </label>
                  <label className="fl-alg !py-2">
                    <input
                      type="checkbox"
                      checked={toggles.summary_enabled}
                      onChange={(e) => setToggle("summary_enabled", e.target.checked)}
                      title="智能摘要：vlm_llm 默认（Qwen-VL-Max + DeepSeek）"
                    />
                    <span className="fl-alg-tt">智能摘要</span>
                  </label>
                  {video?.suggested_params ? (
                    <button
                      type="button"
                      className="fl-act col-span-2"
                      onClick={applySuggested}
                      title={`应用「${video?.suggested_scene_label ?? "智能"}」推荐参数（${((video?.suggested_confidence ?? 0) * 100).toFixed(0)}% 置信度）`}
                    >
                      智能推荐
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="fl-act col-span-2"
                      disabled
                      title="暂无智能推荐（需先运行 smart_suggest）"
                    >
                      智能推荐
                    </button>
                  )}
                </div>
              </>
            ) : (
              <div className="text-[12px] text-gray-400 py-2">加载中…</div>
            )}
          </div>
        </div>

        <div className="fl-drawer-ft">
          <button className="g-btn" onClick={download}><IconDownload />下载</button>
          <button className="g-btn text-red-500 hover:text-red-600 hover:bg-red-50" onClick={() => { if (window.confirm(`确认删除「${file.name}」？`)) { onClose(); onDeleteFile?.(file); } }}><IconTrash />删除</button>
          <span className="flex-1" />
          {/* ── 根据状态动态渲染主按钮 ── */}
          {ps === "pending" && (
            <button className="g-btn g-btn-primary" onClick={() => handleAnalyze(false)} disabled={starting}>
              <IconBolt />视频解析
            </button>
          )}
          {ps === "processing" && (
            <button className="g-btn g-btn-primary" disabled title="解析进行中">
              解析中… {progress != null ? `${Math.round(progress * 100)}%` : ""}
            </button>
          )}
          {ps === "completed" && (
            <button className="g-btn g-btn-primary" onClick={() => handleAnalyze(true)}><IconBoltSolid />重新分析</button>
          )}
          {ps === "failed" && (
            <button className="g-btn g-btn-primary" onClick={() => handleAnalyze(true)} disabled={starting}><IconRetry />重新解析</button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ═══════════════════════ 页面编排 ═══════════════════════ */
export function FileLibrary() {
  const { openWorkbench, uploadFiles, isUploading, refreshCaseGroups, selectedTree, setSelectedTree, videos } = useApp();
  const [files, setFiles] = useState<FileItem[]>([]);
  const [groups, setGroups] = useState<VideoGroup[]>([]);
  /* 案例图片素材已退役（v0.6）：案例库不再支持图片，images 恒空 */
  const [images] = useState<CaseAssetItem[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const tree = selectedTree as TreeKey;
  const [showNewGroup, setShowNewGroup] = useState(false);
  const [form, setForm] = useState({ name: "", number: "", owner: "" });
  const [creatingGroup, setCreatingGroup] = useState(false);
  const creatingGroupRef = useRef(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [analyzing, setAnalyzing] = useState(false);
  const [smartSuggestVids, setSmartSuggestVids] = useState<{ video_id: string; file_name: string }[] | null>(null);
  const [batchTargets, setBatchTargets] = useState<string[] | null>(null);
  /* 案例编辑 */
  const [editCase, setEditCase] = useState<VideoGroup | null>(null);
  const [editForm, setEditForm] = useState({ name: "", number: "", owner: "" });
  const [savingEdit, setSavingEdit] = useState(false);

  /* 案例库正文拖拽上传：选中案例时，拖视频/图片到正文直接上传 */
  const [flDragOver, setFlDragOver] = useState(false);
  const flContainerRef = useRef<HTMLDivElement>(null);
  const flDragDepthRef = useRef(0);
  const activeGroupId = useMemo(() => (tree.startsWith("g:") ? tree.slice(2) : null), [tree]);

  /* ── 递归读取文件夹内容（webkitGetAsEntry API） ── */
  const readEntry = (entry: FileSystemEntry): Promise<File[]> => {
    if (entry.isFile) {
      return new Promise((resolve) => {
        (entry as FileSystemFileEntry).file((f) => resolve([f]), () => resolve([]));
      });
    }
    if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      return new Promise((resolve) => {
        const allFiles: File[] = [];
        const readBatch = () => {
          reader.readEntries(async (entries) => {
            if (entries.length === 0) { resolve(allFiles); return; }
            for (const e of entries) {
              const files = await readEntry(e);
              allFiles.push(...files);
            }
            readBatch(); // 继续读取（readEntries 每次最多返回一批）
          }, () => resolve(allFiles));
        };
        readBatch();
      });
    }
    return Promise.resolve([]);
  };

  const load = () => {
    api.listFiles().then((data) => setFiles(data ?? [])).catch(() => {});
    api.listGroups().then((data) => setGroups(data ?? [])).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
  }, []);

  /* 切换视图（全部/未分组/案例）→ 清空勾选，避免跨范围误批量 */
  useEffect(() => { setSelected(new Set()); }, [tree]);

  const processFiles = async (fileList: File[], gid: string) => {
    const files = Array.from(fileList);
    if (!files.length) return;
    const vids = files.filter((f) => /\.(mp4|mov|avi|mkv|webm)$/i.test(f.name) || f.type.startsWith("video/"));
    const uploadedIds: string[] = [];
    const uploadedEntries: { video_id: string; file_name: string }[] = [];
    if (vids.length) {
      const ids = await uploadFiles(vids, gid, { stay: true });
      uploadedIds.push(...ids);
      /* 用详情拉取文件名（analyzeBatch 也要文件名） */
      for (const id of ids) {
        try {
          const detail = await api.getVideo(id);
          uploadedEntries.push({ video_id: id, file_name: detail.file_name });
        } catch {
          uploadedEntries.push({ video_id: id, file_name: "" });
        }
      }
    }
    load();
    /* 上传视频完成后弹出智能参数推荐弹窗（仅视频 ≥ 1 个；走 stay=true 不会自动跳工作台） */
    if (uploadedEntries.length > 0) setSmartSuggestVids(uploadedEntries);
  };

  const handleUploadFiles = () => {
    if (!tree.startsWith("g:")) { alert("请先选择案例"); return; }
    const gid = tree.slice(2);
    if (!gid || gid === "undefined" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(gid)) {
      alert("案例 ID 异常，请重新选择案例后重试");
      return;
    }
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.multiple = true;
    input.onchange = async () => {
      await processFiles(Array.from(input.files ?? []), gid);
      input.value = "";
    };
    input.click();
  };

  /* 文件夹递归上传：webkitdirectory 让浏览器递归展开子文件夹，FileList 已扁平，忽略相对路径 */
  const handleUploadFolder = () => {
    if (!tree.startsWith("g:")) { alert("请先选择案例"); return; }
    const gid = tree.slice(2);
    if (!gid || gid === "undefined" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(gid)) {
      alert("案例 ID 异常，请重新选择案例后重试");
      return;
    }
    const input = document.createElement("input");
    input.type = "file";
    input.webkitdirectory = true;
    input.multiple = true;
    input.onchange = async () => {
      await processFiles(Array.from(input.files ?? []), gid);
      input.value = "";
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
    creatingGroupRef.current = true;
    try {
      const g = await api.createGroup({ name: form.name.trim(), number: form.number.trim() || undefined, owner: form.owner.trim() || undefined });
      setShowNewGroup(false);
      setForm({ name: "", number: "", owner: "" });
      setSelectedTree(`g:${g.groupId}`);
      await refreshCaseGroups();
      load();
    } catch (err) { alert(err instanceof Error ? err.message : "创建失败"); }
    // 延迟解除锁：等 load() 触发的 setGroups + re-render 全部完成后
    setTimeout(() => { creatingGroupRef.current = false; }, 500);
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
      if (tree === `g:${g.groupId}`) setSelectedTree("all");
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
    } catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };

  /* 树选中失效（组被删）→ 回退第一个案例（新建案例期间跳过） */
  useEffect(() => {
    if (creatingGroupRef.current) return;
    if (groups.length && !groups.some((g) => tree === `g:${g.groupId}`)) {
      setSelectedTree(`g:${groups[0].groupId}`);
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
    if (statusFilter !== "all") {
      list = list.filter((f) => {
        if (statusFilter === "queued") return f.current_status === "pending" && !!f.queued;
        return (f.current_status ?? "pending") === statusFilter;
      });
    }
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

  /* 点「解析」按钮 → 打开原参数设置面板（整批应用同一套参数），确认后整批启动 */
  const handleAnalyze = () => {
    const targets = selected.size > 0 ? Array.from(selected) : displayPendingIds;
    if (targets.length === 0) return;
    setBatchTargets(targets);
  };

  /* 智能推荐弹窗应用入口：多视频共享参数走 analyzeBatch，不确定视频走逐个 PUT /params */
  const handleApplySmartSuggest = async (params: PipelineParams, videoIds: string[]) => {
    setAnalyzing(true);
    try {
      if (videoIds.length >= 2) {
        await api.analyzeBatch(videoIds, params);
      } else {
        await api.updateParams(videoIds[0], { ...params, apply_to_group: false });
      }
      load();
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div
      ref={flContainerRef}
      className={"fl-page h-full flex flex-col gap-2 p-2 relative" + (flDragOver ? " fl-dragover" : "")}
      onDragEnter={(e) => {
        if (!activeGroupId) return;
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        flDragDepthRef.current += 1;
        setFlDragOver(true);
      }}
      onDragOver={(e) => {
        if (!activeGroupId) return;
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={() => {
        flDragDepthRef.current = Math.max(0, flDragDepthRef.current - 1);
        if (flDragDepthRef.current === 0) setFlDragOver(false);
      }}
      onDrop={async (e) => {
        e.preventDefault();
        flDragDepthRef.current = 0;
        setFlDragOver(false);
        if (!activeGroupId) return;
        /* 优先检测 webkitGetAsEntry：支持文件夹递归上传 */
        const items = e.dataTransfer?.items;
        let allFiles: File[] = [];
        if (items && items.length > 0 && 'webkitGetAsEntry' in items[0]) {
          for (let i = 0; i < items.length; i++) {
            const entry = items[i].webkitGetAsEntry();
            if (entry) {
              const files = await readEntry(entry);
              allFiles.push(...files);
            }
          }
        } else {
          allFiles = Array.from(e.dataTransfer?.files ?? []);
        }
        if (!allFiles.length) return;
        /* 与「上传」按钮同逻辑：视频上传后触发智能参数推荐 + 图片上传后立即刷新素材 */
        await processFiles(allFiles, activeGroupId);
      }}
    >
      {flDragOver && activeGroupId && (
        <div className="fl-drop-overlay">
          <div className="fl-drop-box">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <div className="t1">松开上传到当前案例</div>
            <div className="t2">支持视频（MP4/MOV/AVI/MKV/WEBM）、图片（自动识别）和文件夹（递归上传）</div>
          </div>
        </div>
      )}

      {/* ① 顶部卡 */}
      <CaseHeader onNewCase={openNewCase} />

      {/* ② 左卡 + ③ 右卡 */}
      <div className="flex flex-1 gap-2 min-h-0">
        <CaseList
          groups={groups} files={files} tree={tree}
          onSelect={(gid) => setSelectedTree(`g:${gid}`)}
          onDeleteCase={deleteCase}
        />
        <CaseContent
          group={selectedGroup} displayFiles={displayFiles} images={images}
          search={search} statusFilter={statusFilter} tree={tree} isUploading={isUploading}
          selected={selected} allPendingIds={displayPendingIds} analyzing={analyzing}
          onSearch={setSearch} onStatusFilter={setStatusFilter} onUpload={handleUploadFiles}
          onUploadFolder={handleUploadFolder}
          onToggleSelect={toggleSelect} onToggleSelectAll={toggleSelectAll} onAnalyze={handleAnalyze}
          onOpenFile={(f, openParams, reparse) => openWorkbench(f.id, { openParams, reparse })}
          onEditCase={openEditCase}
          onRenameFile={handleRenameFile}
          onRenameAsset={handleRenameAsset}
          onDeleteFile={deleteFile} onDeleteImage={deleteImage}
        />
      </div>

      {/* 上传后智能参数推荐弹窗 */}
      {smartSuggestVids && (
        <SmartSuggestDialog
          videos={smartSuggestVids}
          onClose={() => { setSmartSuggestVids(null); }}
          onApply={async (params, videoIds) => {
            await handleApplySmartSuggest(params, videoIds);
          }}
        />
      )}

      {/* 新建案例弹窗 */}
      {showNewGroup && createPortal(
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
        </div>,
        document.body,
      )}

      {/* 编辑案例弹窗：改 名称/编号/负责人 */}
      {editCase && createPortal(
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
        </div>,
        document.body,
      )}


      {/* 批量解析小弹窗（v0.37）：2 选项（按各视频设置 / 统一参数）替代旧 ParameterPanel */}
      {batchTargets && (
        <BatchAnalyzeDialog
          count={batchTargets.length}
          onClose={() => setBatchTargets(null)}
          onSubmit={async (mode, params) => {
            setAnalyzing(true);
            try {
              if (mode === "per-video") {
                /* Option A：每视频用其自身持久化开关
                   智能推荐上传时已自动落库 6 开关列（confidence ≥ 0.30），
                   所以这里直接走就行 —— 不需要额外 PATCH。 */
                await api.analyzeBatch(batchTargets);
              } else {
                /* Option B：统一参数，整批应用 */
                await api.analyzeBatch(batchTargets, params);
              }
              setSelected(new Set());
              setBatchTargets(null);
              load();
            } catch (err) {
              alert(err instanceof Error ? err.message : "批量解析失败");
              throw err;
            } finally {
              setAnalyzing(false);
            }
          }}
        />
      )}
    </div>
  );
}

/* ═══════════════════════ 批量解析小弹窗（v0.37） ═══════════════════════ */
type BatchMode = "per-video" | "unified";

/* 内容类型场景预设：9 智能推荐场景（v0.37，与 services/smart_suggest.py SCENE_CLASSES 一一对应）
   ⚠️ 摘要默认全关（v0.37）：所有场景预设都不启用摘要（LLM 摘要耗时长且非核心）
   旧值（general/meeting/surveillance/text_recognition）保留兼容历史；custom 不预设，留用户自由配 */
export const CONTENT_TYPE_PRESETS: Record<PipelineParams["content_type"], {
  detection_enabled: boolean; face_enabled: boolean; plate_enabled: boolean;
  ocr_enabled: boolean; search_index_enabled: boolean; summary_enabled: boolean;
} | null> = {
  /* 旧值（兼容历史） */
  general:          { detection_enabled: true,  face_enabled: false, plate_enabled: false, ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  meeting:          { detection_enabled: true,  face_enabled: true,  plate_enabled: false, ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  surveillance:     { detection_enabled: true,  face_enabled: true,  plate_enabled: true,  ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  text_recognition: { detection_enabled: false, face_enabled: false, plate_enabled: false, ocr_enabled: true,  search_index_enabled: false, summary_enabled: false },
  /* 9 智能推荐场景（与 smart_suggest SCENE_CLASSES 一致） */
  traffic:              { detection_enabled: true,  face_enabled: false, plate_enabled: true,  ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  vehicle_focus:        { detection_enabled: true,  face_enabled: false, plate_enabled: true,  ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  surveillance_people:  { detection_enabled: true,  face_enabled: true,  plate_enabled: false, ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  indoor:               { detection_enabled: true,  face_enabled: true,  plate_enabled: false, ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  portrait_focus:       { detection_enabled: true,  face_enabled: true,  plate_enabled: false, ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  document:             { detection_enabled: false, face_enabled: false, plate_enabled: false, ocr_enabled: true,  search_index_enabled: false, summary_enabled: false },
  street_mixed:         { detection_enabled: true,  face_enabled: true,  plate_enabled: true,  ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  outdoor_landscape:    { detection_enabled: true,  face_enabled: false, plate_enabled: false, ocr_enabled: false, search_index_enabled: true,  summary_enabled: false },
  chat_screen:          { detection_enabled: false, face_enabled: false, plate_enabled: false, ocr_enabled: true,  search_index_enabled: false, summary_enabled: false },
  /* custom：用户自由配 */
  custom: null,
};

/* ═══════════════════════ 统一参数面板（可复用） ═══════════════════════ */
/* 内容类型下拉 + 6 开关，受 disabled 控 */
export type UnifiedParams = {
  content_type: PipelineParams["content_type"];
  detection_enabled: boolean; face_enabled: boolean; plate_enabled: boolean;
  ocr_enabled: boolean; search_index_enabled: boolean; summary_enabled: boolean;
};

export function AnalyzeSettingsPanel({
  value, onChange, disabled,
}: {
  value: UnifiedParams;
  onChange: (next: UnifiedParams) => void;
  disabled?: boolean;
}) {
  function changeContentType(next: PipelineParams["content_type"]) {
    const preset = CONTENT_TYPE_PRESETS[next];
    onChange({
      ...value,
      content_type: next,
      ...(preset ?? {}),
    });
  }
  function setToggle(k: "detection_enabled" | "face_enabled" | "plate_enabled" | "ocr_enabled" | "search_index_enabled" | "summary_enabled", v: boolean) {
    const next = { ...value, [k]: v };
    if (k === "detection_enabled" && !v) { next.face_enabled = false; next.plate_enabled = false; }
    onChange(next);
  }

  return (
    <div className={"border border-gray-200 rounded-lg p-3 space-y-2.5 bg-gray-50/60 transition-opacity" + (disabled ? " fl-batch-disabled" : "")}>
      <div>
        <label className="g-label !mb-1">内容类型</label>
        <select
          className="g-input w-full !h-[30px] !text-[12px]"
          value={value.content_type}
          disabled={disabled}
          onChange={(e) => changeContentType(e.target.value as PipelineParams["content_type"])}
        >
          {/* 9 智能推荐场景（与 smart_suggest.py SCENE_CLASSES 对齐）—— 所有场景预设摘要都关 */}
          <option value="traffic">交通监控（车流 + 车牌）</option>
          <option value="vehicle_focus">车辆特写（车 + 车牌）</option>
          <option value="surveillance_people">人流监控（人 + 检测）</option>
          <option value="indoor">室内人物（多人 + 人脸）</option>
          <option value="portrait_focus">人物特写（人脸）</option>
          <option value="document">文档/屏幕（仅 OCR）</option>
          <option value="street_mixed">街景混合（人 + 车 + 车牌）</option>
          <option value="outdoor_landscape">室外空旷/风景（仅检测）</option>
          <option value="chat_screen">聊天记录录屏（仅 OCR）</option>
          <option value="custom">自定义（手动调）</option>
        </select>
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <label className="fl-alg !py-2">
          <input type="checkbox" checked={value.detection_enabled} disabled={disabled} onChange={(e) => setToggle("detection_enabled", e.target.checked)} />
          <span className="fl-alg-tt">物体检测</span>
        </label>
        <label className="fl-alg !py-2">
          <input type="checkbox" checked={value.face_enabled} disabled={disabled || !value.detection_enabled} onChange={(e) => setToggle("face_enabled", e.target.checked)} />
          <span className="fl-alg-tt">人脸</span>
        </label>
        <label className="fl-alg !py-2">
          <input type="checkbox" checked={value.plate_enabled} disabled={disabled || !value.detection_enabled} onChange={(e) => setToggle("plate_enabled", e.target.checked)} />
          <span className="fl-alg-tt">车牌</span>
        </label>
        <label className="fl-alg !py-2">
          <input type="checkbox" checked={value.ocr_enabled} disabled={disabled} onChange={(e) => setToggle("ocr_enabled", e.target.checked)} />
          <span className="fl-alg-tt">OCR 文字</span>
        </label>
        <label className="fl-alg !py-2">
          <input type="checkbox" checked={value.search_index_enabled} disabled={disabled} onChange={(e) => setToggle("search_index_enabled", e.target.checked)} />
          <span className="fl-alg-tt">搜索索引</span>
        </label>
        <label className="fl-alg !py-2">
          <input type="checkbox" checked={value.summary_enabled} disabled={disabled} onChange={(e) => setToggle("summary_enabled", e.target.checked)} />
          <span className="fl-alg-tt">智能摘要</span>
        </label>
      </div>
    </div>
  );
}

/* 把 UnifiedParams 翻译成完整 PipelineParams（其他字段给默认值）
   ⚠️ 摘要默认 false（v0.37） */
export function buildPipelineParams(u: UnifiedParams): PipelineParams {
  return {
    content_type: u.content_type,
    vision_enabled: true,
    audio_enabled: false,
    ocr_enabled: u.ocr_enabled,
    caption_enabled: true,
    detection_enabled: u.detection_enabled,
    detection_classes: null,
    face_enabled: u.face_enabled,
    plate_enabled: u.plate_enabled,
    search_index_enabled: u.search_index_enabled,
    summary_enabled: u.summary_enabled,
    summary_mode: "vlm_llm",
    language: "auto",
    sample_fps: 1.0,
    segment_threshold: 0.5,
    caption_with_context: true,
    summary_detail: "standard",
    encode_profile: null,
    apply_to_group: false,
  };
}

function BatchAnalyzeDialog({
  count, onClose, onSubmit,
}: {
  count: number;
  onClose: () => void;
  onSubmit: (mode: BatchMode, params?: PipelineParams) => Promise<void>;
}) {
  const [mode, setMode] = useState<BatchMode>("per-video");
  const [unified, setUnified] = useState<UnifiedParams>({
    content_type: "outdoor_landscape",
    detection_enabled: true,
    face_enabled: false,
    plate_enabled: false,
    ocr_enabled: false,
    search_index_enabled: true,
    summary_enabled: false,
  });
  const [busy, setBusy] = useState(false);

  async function handleSubmit() {
    if (busy) return;
    setBusy(true);
    try {
      if (mode === "per-video") {
        await onSubmit("per-video");
      } else {
        await onSubmit("unified", buildPipelineParams(unified));
      }
      onClose();
    } catch {
      /* alert 已在外层处理 */
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div className="g-modal-overlay">
      <div className="g-modal" style={{ width: 520, maxHeight: "85vh" }}>
        <div className="g-card-hd">
          <span className="g-card-tt">
            <IconBolt />
            批量解析（{count} 个视频）
          </span>
          <button className="modal-x" onClick={onClose} title="关闭" aria-label="关闭">×</button>
        </div>

        <div className="p-4 space-y-3 overflow-auto">
          {/* ── Option A：按各视频已有设置 ── */}
          <label className={"fl-radio-card" + (mode === "per-video" ? " on" : "")}>
            <input
              type="radio"
              name="batch-mode"
              checked={mode === "per-video"}
              onChange={() => setMode("per-video")}
            />
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-semibold text-gray-900">按各视频设置</div>
              <div className="text-[11.5px] text-gray-500 mt-0.5 leading-relaxed">
                用每个视频自己保存的参数
              </div>
            </div>
          </label>

          {/* ── Option B：统一参数处理 ── */}
          <label className={"fl-radio-card" + (mode === "unified" ? " on" : "")}>
            <input
              type="radio"
              name="batch-mode"
              checked={mode === "unified"}
              onChange={() => setMode("unified")}
            />
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-semibold text-gray-900">统一参数</div>
              <div className="text-[11.5px] text-gray-500 mt-0.5 leading-relaxed">
                用下方一套应用到本批所有视频
              </div>
            </div>
          </label>

          <AnalyzeSettingsPanel value={unified} onChange={setUnified} disabled={mode === "per-video"} />
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-gray-100">
          <button className="g-btn" onClick={onClose} disabled={busy}>取消</button>
          <button className="g-btn g-btn-primary" onClick={handleSubmit} disabled={busy}>
            {busy ? "启动中…" : `开始解析（${count}）`}
          </button>
</div>
      </div>
    </div>,
    document.body,
  );
}


export function SingleAnalyzeDialog({
  title, initial, reparse, onClose, onSubmit,
}: {
  title: string;
  initial: UnifiedParams;
  reparse: boolean;
  onClose: () => void;
  onSubmit: (params: PipelineParams, reparse: boolean) => Promise<void>;
}) {
  const [unified, setUnified] = useState<UnifiedParams>(initial);
  const [busy, setBusy] = useState(false);
  useDisableVideoInteraction();

  async function handleSubmit() {
    if (busy) return;
    setBusy(true);
    try {
      await onSubmit(buildPipelineParams(unified), reparse);
      onClose();
    } catch {
      /* alert 由父组件处理 */
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div className="g-modal-overlay"
      style={{ zIndex: 2147483000, transform: "translateZ(0)", pointerEvents: "auto", backdropFilter: "none" }}>
      <div className="g-modal" style={{ width: 460, maxHeight: "85vh" }}>
        <div className="g-card-hd">
          <span className="g-card-tt">
            <IconBolt />
            {title}
          </span>
          <button className="modal-x" onClick={onClose} title="关闭" aria-label="关闭">×</button>
        </div>
        <div className="p-4 space-y-3 overflow-auto">
          <AnalyzeSettingsPanel value={unified} onChange={setUnified} />
          {reparse && (
            <div className="text-[11.5px] text-amber-600 bg-amber-50 border border-amber-200 rounded px-2.5 py-1.5 leading-relaxed">
              重新解析将基于当前文件创建新版本，旧版本结果仍可查看。
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-gray-100">
          <button className="g-btn" onClick={onClose} disabled={busy}>取消</button>
          <button className="g-btn g-btn-primary" onClick={handleSubmit} disabled={busy}>
            {busy ? "启动中…" : (reparse ? "开始重新解析" : "开始解析")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
