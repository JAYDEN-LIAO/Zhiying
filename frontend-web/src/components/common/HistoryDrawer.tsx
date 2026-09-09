import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../services/api";
import { useTasks } from "../../hooks/useTasks";
import { formatSec } from "../../utils/helpers";
import { IconClose, IconFilm, IconSearch5, IconTrash } from "../icons";
import type { TaskItem } from "../../types";

/* ════════════════════════════════════════════════════════════
   HistoryDrawer — 历史记录抽屉（右侧滑出）
   标题栏带 X 关闭；卡片 = 缩略图 + 三行信息（文件名/算法参数/
   状态徽章+时间戳）；悬停卡片高亮，点击跳转解析页加载视频
   ════════════════════════════════════════════════════════════ */

export function HistoryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { tasks, loading } = useTasks();
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");

  /* 视频时长标签数据源（按文件 ID 匹配文件库） */
  const [durationMap, setDurationMap] = useState<Map<string, number>>(new Map());
  useEffect(() => {
    void api
      .listFiles()
      .then((files) => {
        const m = new Map<string, number>();
        files.forEach((f) => f.duration && m.set(f.id, f.duration));
        setDurationMap(m);
      })
      .catch(() => undefined);
  }, []);

  /* 点击卡片：关闭抽屉 → 解析页加载该视频 */
  const openTask = (id: string) => {
    onClose();
    navigate(`/?video=${id}`);
  };

  const removeTask = (id: string) => {
    setRemoved((s) => new Set(s).add(id));
    setConfirmId(null);
  };

  /* 历史列表：按关键字过滤（文件名/分组名），按创建时间倒序 */
  const kw = keyword.trim().toLowerCase();
  const items = tasks
    .filter((t) => !removed.has(t.id))
    .filter(
      (t) =>
        !kw ||
        (t.file_name ?? "").toLowerCase().includes(kw) ||
        (t.group_name ?? "").toLowerCase().includes(kw),
    )
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

  return (
    <>
      {/* 遮罩 */}
      <div
        className={`fixed inset-0 z-40 bg-black/25 transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={onClose}
      />
      {/* 抽屉主体 */}
      <aside
        className={`fixed right-0 top-0 z-50 flex h-dvh w-[340px] max-w-[92vw] flex-col rounded-l-2xl bg-white shadow-2xl transition-transform duration-300 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* 标题栏（X 关闭） */}
        <div className="flex shrink-0 items-center justify-between border-b border-border-light px-5 py-3.5">
          <p className="text-sm font-semibold text-gray-800">历史记录</p>
          <button
            onClick={onClose}
            title="关闭"
            className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-surface hover:text-gray-600"
          >
            <IconClose />
          </button>
        </div>

        {/* 搜索栏：按文件名/分组名快速定位 */}
        <div className="shrink-0 border-b border-border-light px-4 py-3">
          <div className="flex h-9 items-center gap-2 rounded-lg border border-border-light bg-surface px-3 focus-within:border-primary/50">
            <IconSearch5 className="h-4 w-4 shrink-0 text-gray-400" />
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索文件名 / 分组名…"
              className="min-w-0 flex-1 bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400"
            />
            {keyword && (
              <button
                onClick={() => setKeyword("")}
                className="shrink-0 rounded p-0.5 text-gray-400 transition-colors hover:text-gray-600"
                title="清空"
              >
                <IconClose />
              </button>
            )}
          </div>
        </div>

        {/* 历史卡片列表 */}
        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          {loading && items.length === 0 ? (
            <p className="py-10 text-center text-sm text-gray-400">加载历史记录…</p>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-gray-400">
              <IconFilm />
              <p className="text-sm">{kw ? `没有匹配「${keyword.trim()}」的历史记录` : "暂无历史记录，从文件库选择视频开始解析"}</p>
            </div>
          ) : (
            <ul>
              {items.map((task) => (
                <HistoryCard
                  key={task.id}
                  task={task}
                  duration={durationMap.get(task.id) ?? null}
                  confirming={confirmId === task.id}
                  onOpen={() => openTask(task.id)}
                  onAskDelete={() => setConfirmId(task.id)}
                  onCancelDelete={() => setConfirmId(null)}
                  onConfirmDelete={() => removeTask(task.id)}
                />
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  );
}

/* ── 历史卡片：缩略图 + 三行信息 ── */

function HistoryCard({
  task,
  duration,
  confirming,
  onOpen,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  task: TaskItem;
  duration: number | null;
  confirming: boolean;
  onOpen: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const name = task.file_name ?? "未命名";

  return (
    <li
      onClick={onOpen}
      className="group relative cursor-pointer border-b border-[#E5E7EB] bg-white px-4 py-3 transition-colors first:rounded-t-lg hover:bg-primary/5"
    >
      <div className="flex items-center gap-3">
        {/* 缩略图：视频首帧 + 时长标签 */}
        <div className="relative h-12 w-16 shrink-0 overflow-hidden rounded bg-gray-100">
          <video
            src={api.getVideoStreamUrl(task.id)}
            preload="metadata"
            muted
            className="h-full w-full object-cover"
          />
          {duration != null && (
            <span className="absolute bottom-0.5 right-0.5 rounded-sm bg-black/60 px-1 text-[10px] leading-4 text-white">
              {formatSec(duration)}
            </span>
          )}
        </div>

        {/* 信息区：三行式 */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 第一行：文件名 + 删除按钮 */}
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-bold text-[#1F2937]" title={name}>
              {name}
            </p>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAskDelete();
              }}
              title="删除该记录"
              className="shrink-0 rounded p-1 text-gray-300 transition-colors group-hover:text-red-500 hover:bg-red-50"
            >
              <IconTrash />
            </button>
          </div>

          {/* 第二行：算法类型 + 处理参数 */}
          <p className="mt-0.5 truncate text-xs text-[#6B7280]">{metaLine(task)}</p>

          {/* 第三行：状态徽章 + 时间戳 */}
          <div className="mt-1 flex items-center justify-between">
            <HistoryStatus task={task} />
            <span className="text-xs text-[#9CA3AF]">{formatStamp(task.created_at)}</span>
          </div>
        </div>
      </div>

      {/* 删除二次确认浮层 */}
      {confirming && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-3 top-2 z-10 flex items-center gap-1.5 rounded-lg border border-border-light bg-white px-2.5 py-1.5 shadow-lg"
        >
          <span className="text-xs text-gray-500">删除该记录？</span>
          <button onClick={onConfirmDelete} className="rounded bg-red-500 px-2 py-0.5 text-xs text-white hover:bg-red-600">
            删除
          </button>
          <button onClick={onCancelDelete} className="rounded px-2 py-0.5 text-xs text-gray-400 hover:bg-surface">
            取消
          </button>
        </div>
      )}
    </li>
  );
}

/* 算法属性行：类型 | 能力组合 | 采样帧率 */
function metaLine(task: TaskItem): string {
  const p = task.params as Record<string, unknown> | null;
  const type = p?.content_type === "general" || !p?.content_type ? "通用" : String(p.content_type);
  const fps = p?.sample_fps != null ? `${Number(p.sample_fps).toFixed(1)}fps` : "1.0fps";
  const feats: string[] = [];
  if (p?.search_index_enabled !== false) feats.push("搜索");
  if (p?.summary_enabled) feats.push("摘要");
  if (p?.detection_enabled) feats.push("检测");
  if (p?.face_enabled) feats.push("人脸");
  if (p?.plate_enabled) feats.push("车牌");
  return `${type} | ${feats.length > 0 ? feats.join("+") : "搜索"} | ${fps}`;
}

/* 状态徽章：已完成（绿）/ 解析中（蓝+进度）/ 失败（红，悬停看原因）/ 排队（灰） */
function HistoryStatus({ task }: { task: TaskItem }) {
  if (task.status === "completed") {
    return (
      <span className="rounded-full bg-[#10B981]/10 px-2 py-0.5 text-[11px] font-medium text-[#10B981]">已完成</span>
    );
  }
  if (task.status === "processing") {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-primary">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        解析中 {Math.round(task.progress)}%
      </span>
    );
  }
  if (task.status === "failed") {
    return (
      <span
        title={task.error_message ?? "解析失败"}
        className="cursor-help rounded-full bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-500"
      >
        失败
      </span>
    );
  }
  return <span className="text-[11px] text-gray-400">排队中</span>;
}

/* 时间戳：M/D HH:mm（本地时区） */
function formatStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
