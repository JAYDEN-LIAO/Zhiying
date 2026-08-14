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
import type { FileItem, VideoGroup, CaseAssetItem, PipelineParams } from "../types";
import { fmtDuration, fmtDate, fmtBytes } from "../utils/helpers";
import { IconFolder, IconPlus, IconPlay2, IconTrash, IconPencil, IconBolt, IconBoltSolid, IconEye } from "./icons";
import { ParameterPanel } from "./ParameterPanel";

type TreeKey = "all" | "ungrouped" | `g:${string}`;

const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待处理", cls: "wait" },
  processing: { label: "处理中", cls: "run", pulse: true },
  completed: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

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

/* ═══════════════════════ ① 顶部卡 ═══════════════════════ */
function CaseHeader({ onNewCase }: { onNewCase: () => void }) {
  return (
    <div className="case-card flex items-center justify-between flex-wrap gap-y-1.5 px-5 py-2 min-h-[56px] shrink-0">
      <div>
        <h1 className="text-[16px] font-semibold text-gray-900 leading-tight">案例库</h1>
        <p className="text-[12px] text-gray-500 leading-tight">案例素材归档</p>
      </div>
      <button className="g-btn g-btn-primary" onClick={onNewCase}>
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 3h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" /></svg>
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
        {groups.length === 0 && <div className="g-empty"><span>暂无案例，点击「新建案例」</span></div>}
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
            className="g-input !w-[130px] !h-[30px] !text-[12px]" placeholder="检索文件"
            value={search} onChange={(e) => onSearch(e.target.value)}
          />
          <select className="g-input !w-[110px] !h-[30px] !text-[12px]" value={statusFilter} onChange={(e) => onStatusFilter(e.target.value)}>
            <option value="all">全部状态</option>
            <option value="pending">待处理</option>
            <option value="processing">处理中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
          </select>
          {/* 上传文件：白底 outline（与新建案例蓝色等大） */}
          <button className="g-btn" onClick={onUpload} disabled={isUploading}>
            <IconPlus />
            {isUploading ? "上传中..." : "上传文件"}
          </button>
          {/* 一键解析：未勾选 → 处理当前列表全部待处理；勾选后 → 批量解析勾选的 */}
          <button className="g-btn g-btn-primary" onClick={onAnalyze}
            disabled={analyzing || (selected.size === 0 && allPendingIds.length === 0)} title="配置参数并启动待处理视频">
            <IconPlay2 />
            {selected.size > 0 ? `批量解析 (${selected.size})` : `一键解析 (${allPendingIds.length})`}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
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
              const sm = STATUS_META[f.current_status ?? "pending"] || STATUS_META.pending;
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
                    <span className={"g-badge " + sm.cls}>
                      {sm.pulse && <span className="pulse" />}
                      {sm.label}
                      {f.current_status === "completed" && (f.versions_count ?? 1) > 1 && (
                        <span className="opacity-80"> · 共 {f.versions_count} 版</span>
                      )}
                    </span>
                  </td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    <div className="inline-flex items-center gap-1.5">
                      {/* 四个操作：编辑(重命名) → 解析(闪电) → 预览/结果 → 删除 */}
                      <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors" title="重命名文件"
                        onClick={() => startEdit("file", f.id, splitName(f.name, f.file_ext).base)}>
                        <IconPencil />
                      </button>
                      {/* 闪电对所有状态显示：已完成 = 实心 + 重新配置参数解析（走 reanalyze 建新版本）；未完成 = 描边 + 配置参数启动 */}
                      <button className="p-1.5 rounded-md text-[#4f7cff] hover:bg-blue-50 transition-colors"
                        title={f.current_status === "completed" ? "重新配置参数解析" : "配置参数并解析"}
                        onClick={() => onOpenFile(f, true, f.current_status === "completed")}>
                        {f.current_status === "completed" ? <IconBoltSolid /> : <IconBolt />}
                      </button>
                      {/* 预览/查看结果合并为一个眼睛按钮：未处理=预览，已完成=查看结果 */}
                      <button className="p-1.5 rounded-md text-gray-500 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors"
                        title={f.current_status === "completed" ? "查看结果" : "预览视频"}
                        onClick={() => onOpenFile(f, false)}>
                        <IconEye />
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
                      <button className="p-1.5 rounded-md text-gray-500 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors" title="预览图片"
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
        {displayFiles.length === 0 && images.length === 0 && (
          <div className="g-empty">
            <IconFolder />
            <span>{search || statusFilter !== "all" ? "当前筛选下暂无文件" : "点击「上传文件」归档视频/图片到此案例"}</span>
          </div>
        )}
      </div>

      {/* 图片预览弹窗 */}
      {previewImg && group && (
        <div className="g-modal-overlay" onClick={() => setPreviewImg(null)}>
          <div className="g-modal" style={{ maxWidth: "70vw" }} onClick={(e) => e.stopPropagation()}>
            <div className="g-card-hd">
              <span className="g-card-tt">{previewImg.name}</span>
              <button className="g-btn g-btn-sm" onClick={() => setPreviewImg(null)}>关闭</button>
            </div>
            <div className="p-4 flex items-center justify-center bg-gray-50" style={{ minHeight: 320 }}>
              <img src={api.getAssetFileUrl(group.groupId, previewImg.id)} alt={previewImg.name}
                style={{ maxWidth: "100%", maxHeight: "62vh", objectFit: "contain" }} />
            </div>
          </div>
        </div>
      )}
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
  const [batchTargets, setBatchTargets] = useState<string[] | null>(null);
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
      if (vids.length) await uploadFiles(vids, gid, { stay: true });
      if (imgs.length) {
        try { await api.uploadGroupAssets(gid, imgs); } catch (err) { alert(err instanceof Error ? err.message : "图片上传失败"); }
      }
      try {
        const d = await api.getGroupAssets(gid);
        setImages(d?.images ?? []);
      } catch { /* ignore */ }
      load();
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
    if (statusFilter !== "all") list = list.filter((f) => f.current_status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((f) => f.name.toLowerCase().includes(q));
    }
    return list;
  }, [treeFiltered, statusFilter, search]);

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

  /* 点按钮 → 打开参数面板（同一批应用一套参数），确认后整批启动 */
  const handleAnalyze = () => {
    const targets = selected.size > 0 ? Array.from(selected) : displayPendingIds;
    if (targets.length === 0) return;
    setBatchTargets(targets);
  };

  const handleBatchSubmit = async (params: PipelineParams) => {
    if (!batchTargets) return;
    setAnalyzing(true);
    try {
      const r = await api.analyzeBatch(batchTargets, params);
      setSelected(new Set());
      setBatchTargets(null);
      load();
      alert(`已提交 ${r.started} 个任务${r.skipped > 0 ? `，跳过 ${r.skipped} 个` : ""}`);
    } catch (err) {
      throw err instanceof Error ? err : new Error("批量解析失败");
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
              <button className="g-btn g-btn-sm" onClick={() => setShowNewGroup(false)}>×</button>
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
              <button className="g-btn g-btn-sm" onClick={() => setEditCase(null)}>×</button>
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

      {/* 批量解析参数面板：整批应用同一套参数 */}
      {batchTargets && (
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ height: "min(620px, 82vh)" }}>
            <ParameterPanel
              batchCount={batchTargets.length}
              onBatchSubmit={handleBatchSubmit}
              onParamsSet={() => {}}
              onClose={() => setBatchTargets(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
