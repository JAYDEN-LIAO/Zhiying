/* ════════════════════════════════════════════════════════════
   FileLibrary — 文件库（v0.34 桌面重构 · 照 demo CaseLibrary 结构）
   顶栏（标题+检索+上传） + 左侧视频分组树 + 右侧文件表格
   （类型/文件名/时长/上传时间/状态/操作：查看结果/智能解析/预览/删除）
   ════════════════════════════════════════════════════════════ */

import { useMemo, useState } from "react";
import { useApp } from "../AppContext";
import type { VideoListItem } from "../types";
import { fmtDuration, fmtDate } from "../utils/helpers";
import { IconFolder } from "./icons";

const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待参数", cls: "wait" },
  processing: { label: "处理中", cls: "run", pulse: true },
  completed: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

const STATUS_OPTIONS = [
  { value: "all", label: "全部状态" },
  { value: "pending", label: "待参数" },
  { value: "processing", label: "处理中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
];

type TreeKey = "all" | "ungrouped" | `g:${string}`;

function VideoIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0 1 21 8.618v6.764a1 1 0 0 1-1.447.894L15 14M5 18h8a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2z" />
    </svg>
  );
}

export function FileLibrary() {
  const { videos, videoGroups, selectedVideoId, openWorkbench, deleteVideo, handleUploadClick, isUploading } = useApp();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [tree, setTree] = useState<TreeKey>("all");
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  /* ── 分组树节点 ── */
  const treeNodes = useMemo(() => {
    const nodes: { key: TreeKey; label: string; count: number }[] = [
      { key: "all", label: "全部视频", count: videos.length },
    ];
    videoGroups.forEach((g, i) => {
      const first = videos.find((v) => v.id === g.videoIds[0]);
      const label = first ? first.file_name.slice(0, 8) + "…" : `分组 ${i + 1}`;
      nodes.push({ key: `g:${g.groupId}`, label, count: g.videoIds.length });
    });
    const ungrouped = videos.filter((v) => !v.group_id).length;
    nodes.push({ key: "ungrouped", label: "未分组", count: ungrouped });
    return nodes;
  }, [videos, videoGroups]);

  /* ── 当前树节点下的视频 ── */
  const treeFiltered = useMemo(() => {
    if (tree === "all") return videos;
    if (tree === "ungrouped") return videos.filter((v) => !v.group_id);
    const gid = tree.slice(2);
    return videos.filter((v) => v.group_id === gid);
  }, [tree, videos]);

  const displayVideos = useMemo(() => {
    let list = treeFiltered;
    if (statusFilter !== "all") list = list.filter((v) => v.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((v) => v.file_name.toLowerCase().includes(q));
    }
    return list;
  }, [treeFiltered, statusFilter, search]);

  const currentLabel = treeNodes.find((n) => n.key === tree)?.label ?? "全部视频";

  const handleDelete = async (v: VideoListItem) => {
    if (!window.confirm(`确认删除「${v.file_name}」？将同时释放磁盘空间。`)) return;
    setDeletingIds((prev) => new Set(prev).add(v.id));
    try { await deleteVideo(v.id); }
    catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
    setDeletingIds((prev) => { const n = new Set(prev); n.delete(v.id); return n; });
  };

  return (
    <div className="h-full flex flex-col">
      {/* ══ 顶栏 ══ */}
      <div className="h-[52px] px-5 bg-white border-b border-gray-200 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-[15px] font-semibold text-gray-900 leading-tight">文件库</h1>
          <p className="text-[11.5px] text-gray-400 leading-tight">视频数据资产管理中心 · 按分组归档管理</p>
        </div>
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <svg className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input className="g-input !w-[240px] !pl-8" placeholder="文件检索" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <button className="g-btn g-btn-primary" onClick={handleUploadClick} disabled={isUploading}>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><path strokeLinecap="round" d="M12 4v16m8-8H4" /></svg>
            {isUploading ? "上传中..." : "上传视频"}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex">
        {/* ══ 左侧视频分组树 ══ */}
        <aside className="w-[260px] shrink-0 bg-white border-r border-gray-200 flex flex-col min-h-0">
          <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between shrink-0">
            <span className="text-[12px] font-semibold text-gray-500">视频分组</span>
            <span className="text-[11.5px] text-gray-400">{videoGroups.length + (videos.some((v) => !v.group_id) ? 1 : 0) + 1} 项</span>
          </div>
          <div className="flex-1 overflow-auto py-1.5">
            {treeNodes.map((n) => (
              <div
                key={n.key}
                className={"mx-1.5 px-3 py-2 rounded-md cursor-pointer border-l-[3px] " + (tree === n.key ? "bg-brand/5 border-[#4f7cff]" : "border-transparent hover:bg-gray-50")}
                onClick={() => setTree(n.key)}
              >
                <div className="flex items-center gap-2">
                  <span className={tree === n.key ? "text-[#4f7cff]" : "text-gray-400"}><IconFolder /></span>
                  <span className={"text-[13px] truncate flex-1 " + (tree === n.key ? "text-[#4f7cff] font-semibold" : "text-gray-800")}>{n.label}</span>
                  <span className="text-[11px] text-gray-400 bg-gray-100 rounded-full px-1.5 py-0.5">{n.count}</span>
                </div>
              </div>
            ))}
            {treeNodes.length === 0 && <div className="g-empty"><span>暂无视频</span></div>}
          </div>
        </aside>

        {/* ══ 右侧文件表格 ══ */}
        <section className="flex-1 min-w-0 flex flex-col bg-white min-h-0">
          <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2.5">
              <span className="text-[13px] font-semibold text-gray-900">{currentLabel}</span>
              <span className="text-[11.5px] text-gray-400">{displayVideos.length} 个视频</span>
              <select className="g-input !w-[120px] !h-[30px] !text-[12px]" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <button className="g-btn" onClick={handleUploadClick} disabled={isUploading}>
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 8l5-5 5 5m-5-5v11" /></svg>
              {isUploading ? "上传中..." : "上传文件"}
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-auto">
            <table className="g-table">
              <thead>
                <tr>
                  <th className="w-10">类型</th>
                  <th>文件名</th>
                  <th className="w-24">时长</th>
                  <th className="w-36">上传时间</th>
                  <th className="w-28">状态</th>
                  <th className="w-[240px] text-right pr-4">操作</th>
                </tr>
              </thead>
              <tbody>
                {displayVideos.map((v) => {
                  const sm = STATUS_META[v.status] || STATUS_META.pending;
                  const hasResult = v.status === "completed";
                  return (
                    <tr key={v.id} style={{ opacity: deletingIds.has(v.id) ? 0.5 : 1 }}>
                      <td>
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded bg-gray-50 text-gray-500"><VideoIcon /></span>
                      </td>
                      <td className="text-gray-800 max-w-[320px] truncate" title={v.file_name}>{v.file_name}</td>
                      <td className="text-gray-500">{v.duration != null ? fmtDuration(v.duration) : "-"}</td>
                      <td className="text-gray-500">{fmtDate(v.created_at)}</td>
                      <td>
                        <span className={"g-badge " + sm.cls}>
                          {sm.pulse && <span className="pulse" />}
                          {sm.label}
                        </span>
                      </td>
                      <td className="text-right pr-4 whitespace-nowrap">
                        <button
                          className="g-btn g-btn-primary !px-2 !py-1 mr-1"
                          title={hasResult ? "打开工作台查看结果" : "配置参数并解析"}
                          onClick={() => openWorkbench(v.id, { openParams: !hasResult })}
                        >
                          {hasResult ? "查看结果" : "智能解析"}
                        </button>
                        <button className="g-btn !px-2 !py-1 mr-1" title="预览" onClick={() => openWorkbench(v.id)}>
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                          预览
                        </button>
                        <button className="g-btn g-btn-danger !px-2 !py-1" onClick={() => handleDelete(v)}>删除</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {displayVideos.length === 0 && (
              <div className="g-empty">
                <IconFolder />
                <span>{search || statusFilter !== "all" ? "当前筛选下暂无视频" : "拖拽视频文件到此处，或点击「上传视频」批量归档"}</span>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
