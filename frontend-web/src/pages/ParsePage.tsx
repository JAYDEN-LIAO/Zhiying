import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../services/api";
import { MOCK_FILE_TAGS } from "../services/mock";
import { PlayerPanel } from "../components/workbench/PlayerPanel";
import { SummaryPanel } from "../components/workbench/SummaryPanel";
import { DetectionPanel } from "../components/workbench/DetectionPanel";
import { SearchPanel } from "../components/workbench/SearchPanel";
import { SplitPane } from "../components/common/SplitPane";
import { StatusBadge } from "../components/common/StatusBadge";
import { FilePickerModal, type FilePickResult } from "../components/common/FilePickerModal";
import { IconChevronDown, IconClose, IconPlus, IconSearch5, IconVideo } from "../components/icons";
import type { DetectionData, FileItem, VideoResponse } from "../types";

/* ════════════════════════════════════════════════════════════
   ParsePage — 智能解析（单页双视图）
   列表视图（无 ?video 参数）：高密度网格（只展示已完成）
     顶部操作区：搜索框（按文件名过滤）+ [➕ 新建解析] 主按钮
     任务进度折叠面板：处理中/待处理/失败任务，不混排结果列表
     卡片：状态标签 + AI 结构化标签 + 文件名 + 日期/时长
   详情视图（?video=<id>，三列可拖拽调宽）：
     左列：视频播放器（Canvas 识别框 + 事件标记进度条）
     右侧区域（1+2）：视频摘要 | 物体检测(40%) + 视频搜索(60%)
   URL 参数：?video=<id>&t=<秒>&refresh=<ts>
   ════════════════════════════════════════════════════════════ */

export function ParsePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const videoId = params.get("video") ?? "";
  const tParam = params.get("t");
  const refreshParam = params.get("refresh");

  const videoRef = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<VideoResponse | null>(null);
  const [detections, setDetections] = useState<DetectionData | null>(null);
  const [seekTo, setSeekTo] = useState<number | null>(tParam != null ? Number(tParam) : null);
  const [currentTime, setCurrentTime] = useState(0);
  const [pickerOpen, setPickerOpen] = useState(false);

  /* 列表视图状态：文件库 + 搜索关键字 + Toast + 任务面板折叠 + 筛选器 */
  const [files, setFiles] = useState<FileItem[] | null>(null); // null = 加载中
  const [keyword, setKeyword] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [tasksCollapsed, setTasksCollapsed] = useState(false);
  /* 状态筛选（下拉 + 快捷胶囊共用）：默认「全部」 */
  const [statusFilter, setStatusFilter] = useState<"all" | "video" | "queued" | "processing" | "completed" | "failed">("all");
  const [tagFilter, setTagFilter] = useState<string>("all"); // all = 全部标签
  const [sortKey, setSortKey] = useState<"newest" | "oldest" | "duration" | "name">("newest");

  /* 列表数据：首次加载 + 4s 轮询（处理进度/完成状态实时更新） */
  useEffect(() => {
    if (videoId) return;
    let cancelled = false;
    const load = () =>
      api
        .listFiles()
        .then((d) => {
          if (!cancelled) setFiles(d);
        })
        .catch(() => {
          if (!cancelled) setFiles([]);
        });
    load();
    const timer = setInterval(load, 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [videoId]);

  /* Toast 自动消失 */
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  /* URL 参数变化（含 refresh / 更换视频）→ 重置状态并应用初始 seek */
  useEffect(() => {
    setVideo(null);
    setDetections(null);
    setCurrentTime(0);
    setSeekTo(tParam != null && !Number.isNaN(Number(tParam)) ? Number(tParam) : null);
  }, [videoId, tParam, refreshParam]);

  /* 视频详情：处理中每 3s 轮询，完成后停止 */
  useEffect(() => {
    if (!videoId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      api
        .getVideo(videoId)
        .then((data) => {
          if (cancelled) return;
          setVideo(data);
          if (data.status === "pending" || data.status === "processing") {
            timer = setTimeout(load, 3000);
          }
        })
        .catch(() => {
          if (!cancelled) setVideo(null);
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [videoId, refreshParam]);

  /* 解析完成后拉取检测轨迹 */
  useEffect(() => {
    if (!video || video.status !== "completed" || !video.id) {
      setDetections(null);
      return;
    }
    let cancelled = false;
    api
      .fetchDetectionTracks(video.id)
      .then((d) => {
        if (!cancelled) setDetections(d);
      })
      .catch(() => {
        if (!cancelled) setDetections(null);
      });
    return () => {
      cancelled = true;
    };
  }, [video?.id, video?.status]);

  /* 统一 seek 入口：播放器就绪直接跳，未就绪交给 PlayerPanel 挂起 */
  const handleSeek = (sec: number) => {
    const el = videoRef.current;
    if (el && el.readyState >= 1) {
      el.currentTime = sec;
      void el.play().catch(() => {});
    } else {
      setSeekTo(sec);
    }
  };

  /* 文件库单选 → 立即进入解析详情页（同路由参数变化，原地刷新） */
  const pickFromLibrary = (result: FilePickResult) => {
    const id = result.videoIds[0];
    if (id) navigate(`/?video=${id}`);
  };

  /* ── 列表视图：筛选区三行结构 + 高密度网格 ── */
  if (!videoId) {
    const kw = keyword.trim().toLowerCase();

    /* 状态视图（下拉 + 快捷胶囊共用单一状态源）→ 文件状态集合（null = 不过滤） */
    const STATUS_MATCH: Record<string, string[] | null> = {
      all: null,
      video: null,
      queued: ["pending", "queued"],
      processing: ["processing"],
      completed: ["completed"],
      failed: ["failed"],
    };
    const statusSet = STATUS_MATCH[statusFilter] ?? null;

    /* 标签筛选：AI 结构化标签去重集合 */
    const allTags = Array.from(
      new Set((files ?? []).flatMap((f) => MOCK_FILE_TAGS[f.id] ?? [])),
    ).sort();

    /* 过滤管线：关键字 → 状态 → 标签 → 排序 */
    const pipeline = (files ?? [])
      .filter((f) => !kw || f.name.toLowerCase().includes(kw))
      .filter((f) => !statusSet || statusSet.includes(f.current_status ?? "pending"))
      .filter((f) => tagFilter === "all" || (MOCK_FILE_TAGS[f.id] ?? []).includes(tagFilter));
    const items =
      sortKey === "newest"
        ? [...pipeline].sort((a, b) => (a.created_at ?? "") < (b.created_at ?? "") ? 1 : -1)
        : sortKey === "oldest"
          ? [...pipeline].sort((a, b) => (a.created_at ?? "") > (b.created_at ?? "") ? 1 : -1)
          : sortKey === "duration"
            ? [...pipeline].sort((a, b) => (b.duration ?? 0) - (a.duration ?? 0))
            : [...pipeline].sort((a, b) => a.name.localeCompare(b.name));

    /* 任务面板：仅当列表筛到「已完成」时出现（活跃任务不混排结果列表） */
    const activeTasks = (files ?? [])
      .filter((f) => f.current_status !== "completed")
      .sort((a, b) => (a.current_status === "processing" ? -1 : 0) - (b.current_status === "processing" ? -1 : 0));
    const processingCount = (files ?? []).filter((f) => f.current_status === "processing").length;

    return (
      <div className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 px-6 pb-3 pt-4">
          <div className="flex items-center">
            <h1 className="text-lg font-semibold text-gray-900">智能解析</h1>
            <div className="flex-1" />
            <button onClick={() => setPickerOpen(true)} className="g-btn g-btn-primary shrink-0 px-4 py-2 text-sm">
              <IconPlus />
              新建解析
            </button>
          </div>

          {/* 第一行（通栏搜索区）：宽大圆角矩形搜索框 + 右侧搜索按钮 */}
          <div className="mt-3 flex h-11 items-center gap-2.5 rounded-xl border border-[#c9d6f2] bg-[#f4f7fe] pl-4 pr-1.5 shadow-sm transition-all focus-within:border-primary/70 focus-within:shadow-md">
            <IconSearch5 className="h-[18px] w-[18px] shrink-0 text-gray-500" />
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setToast(keyword.trim() ? "已按当前关键字过滤列表" : "请输入搜索关键字");
              }}
              placeholder="搜索视频 / 标签 / 元数据..."
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
            {/* 最右侧搜索按钮：明确触发查询 */}
            <button
              onClick={() => setToast(keyword.trim() ? "已按当前关键字过滤列表" : "请输入搜索关键字")}
              title="搜索"
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary/90"
            >
              <IconSearch5 className="h-4 w-4" />
              搜索
            </button>
          </div>

          {/* 第二行（筛选操作栏）+ 第三段（快捷过滤标签组）：同一水平基准线 */}
          <div className="mt-3 flex items-center gap-4">
            {/* 区块一：状态筛选 */}
            <FilterDropdown
              label="状态"
              value={STATUS_OPTIONS.find((o) => o.value === statusFilter)?.label ?? "全部"}
              options={STATUS_OPTIONS}
              onSelect={(v) => setStatusFilter(v as typeof statusFilter)}
            />
            <span className="h-4 w-px shrink-0 bg-border-light" />
            {/* 区块二：标签筛选 */}
            <FilterDropdown
              label="标签"
              value={tagFilter === "all" ? "全部" : tagFilter}
              options={[{ value: "all", label: "全部" }, ...allTags.map((t) => ({ value: t, label: t }))]}
              onSelect={setTagFilter}
            />
            <span className="h-4 w-px shrink-0 bg-border-light" />
            {/* 区块三：排序筛选 */}
            <FilterDropdown
              label="排序"
              value={SORT_OPTIONS.find((o) => o.value === sortKey)?.label ?? "最新上传"}
              options={SORT_OPTIONS}
              onSelect={(v) => setSortKey(v as typeof sortKey)}
            />

            {/* 极细分隔线隔开快捷过滤标签组（与状态筛选联动） */}
            <span className="h-4 w-px shrink-0 bg-border-light" />
            <div className="flex items-center gap-2">
              {QUICK_CHIPS.map((c) => (
                <button
                  key={c.value}
                  onClick={() => setStatusFilter(c.value as typeof statusFilter)}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                    statusFilter === c.value
                      ? "bg-primary text-white shadow-sm"
                      : "bg-white text-gray-600 shadow-sm hover:text-primary"
                  }`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* 任务进度折叠面板：仅当列表筛到「已完成」时出现（活跃任务不混排） */}
        {statusFilter === "completed" && activeTasks.length > 0 && (
          <div className="mx-6 shrink-0 overflow-hidden rounded-card bg-white shadow-card">
            <button
              onClick={() => setTasksCollapsed((v) => !v)}
              className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
            >
              <span
                className={`inline-block shrink-0 text-gray-400 transition-transform ${tasksCollapsed ? "" : "rotate-180"}`}
              >
                <IconChevronDown />
              </span>
              <span className="text-sm font-medium text-gray-700">解析任务</span>
              <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[11px] font-medium text-primary">
                {processingCount} 个进行中
              </span>
            </button>
            {!tasksCollapsed && (
              <ul className="divide-y divide-border-light border-t border-border-light">
                {activeTasks.map((f) => (
                  <li
                    key={f.id}
                    onClick={() =>
                      setToast(f.current_status === "failed" ? "视频解析失败，无法查看" : "正在解析中，请稍候")
                    }
                    className="flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors hover:bg-primary/5"
                  >
                    <StatusTag status={f.current_status ?? "pending"} />
                    <span className="min-w-0 flex-1 truncate text-sm text-gray-700">{f.name}</span>
                    {f.current_status === "processing" ? (
                      <div className="flex w-44 shrink-0 items-center gap-2">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                          <div
                            className="h-full rounded-full bg-primary transition-all duration-500"
                            style={{ width: `${Math.min(100, f.current_progress ?? 0)}%` }}
                          />
                        </div>
                        <span className="w-8 text-right text-xs tabular-nums text-primary">
                          {f.current_progress ?? 0}%
                        </span>
                      </div>
                    ) : f.current_status === "failed" ? (
                      <span className="shrink-0 text-xs text-red-400">解析失败</span>
                    ) : (
                      <span className="shrink-0 text-xs text-gray-400">排队中</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* 主体：视频紧凑卡片网格 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-5 pt-3">
          {files == null ? (
            <p className="py-16 text-center text-sm text-gray-400">加载视频列表…</p>
          ) : items.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary-soft text-primary">
                <IconVideo className="h-8 w-8" />
              </div>
              <p className="text-sm text-gray-400">
                {files.length === 0 ? "暂无解析结果，请点击右上角新建解析" : "没有符合当前筛选条件的视频"}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(216px,1fr))] gap-3">
              {items.map((f) => (
                <VideoCard
                  key={f.id}
                  file={f}
                  clickable={f.current_status === "completed"}
                  onOpen={() => navigate(`/?video=${f.id}`)}
                  onBlock={(msg) => setToast(msg)}
                />
              ))}
            </div>
          )}
        </div>

        <Toast message={toast} />
        <FilePickerModal mode="single" open={pickerOpen} onClose={() => setPickerOpen(false)} onConfirm={pickFromLibrary} />
      </div>
    );
  }

  /* ── 详情视图：三列可拖拽（播放器 | 物体检测 | 视频搜索） ── */
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 页头：文件名 + 状态 */}
      <header className="flex shrink-0 items-center gap-3 px-6 pb-3 pt-4">
        <h1 className="shrink-0 text-lg font-semibold text-gray-900">智能解析</h1>
        {video && (
          <>
            <span className="min-w-0 truncate text-sm text-gray-500">{video.file_name}</span>
            <StatusBadge status={video.status} />
          </>
        )}
      </header>

      <div className="flex min-h-0 flex-1 px-6 pb-5">
        {/* 左列：播放器 | 右侧区域（顶部摘要 + 底部检测/搜索） */}
        <SplitPane
          direction="row"
          initial={58}
          min={30}
          max={80}
          className="h-full w-full"
          first={
            <PlayerPanel
              video={video}
              detections={detections}
              videoRef={videoRef}
              currentTime={currentTime}
              onTimeUpdate={setCurrentTime}
              seekTo={seekTo}
              onSeek={handleSeek}
            />
          }
          second={
            /* 1+2：顶部视频摘要（22%）+ 底部物体检测/视频搜索 */
            <SplitPane
              direction="col"
              initial={22}
              min={10}
              max={45}
              className="h-full"
              first={<SummaryPanel video={video} />}
              second={
                <SplitPane
                  direction="row"
                  initial={40}
                  min={25}
                  max={65}
                  className="h-full"
                  first={<DetectionPanel video={video} detections={detections} onSeek={handleSeek} />}
                  second={<SearchPanel videoId={video?.id ?? videoId} onSeek={handleSeek} />}
                />
              }
            />
          }
        />
      </div>

      <FilePickerModal mode="single" open={pickerOpen} onClose={() => setPickerOpen(false)} onConfirm={pickFromLibrary} />
    </div>
  );
}

/* ── 筛选选项常量 ── */

const STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "queued", label: "排队中" },
  { value: "processing", label: "处理中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
];

const SORT_OPTIONS = [
  { value: "newest", label: "最新上传" },
  { value: "oldest", label: "最早上传" },
  { value: "duration", label: "时长最长" },
  { value: "name", label: "文件名" },
];

const QUICK_CHIPS = [
  { value: "all", label: "全部" },
  { value: "video", label: "视频" },
  { value: "queued", label: "排队中" },
  { value: "completed", label: "已完成" },
];

/* ── 紧凑视频卡片：缩略图 + AI 结构化标签 + 文件名 + 日期 ── */
function VideoCard({
  file,
  clickable,
  onOpen,
  onBlock,
}: {
  file: FileItem;
  clickable: boolean;
  onOpen: () => void;
  onBlock: (msg: string) => void;
}) {
  const tags = MOCK_FILE_TAGS[file.id] ?? [];

  /* 已完成进入详情；其余状态阻断并提示 */
  const handleClick = () => {
    if (file.current_status === "completed") onOpen();
    else if (file.current_status === "failed") onBlock("视频解析失败，无法查看");
    else onBlock("正在解析中，请稍候");
  };

  return (
    <div
      onClick={handleClick}
      className={`group flex cursor-pointer flex-col rounded-xl bg-white p-3 shadow-card transition-all ${
        clickable ? "hover:-translate-y-0.5 hover:shadow-lg" : "opacity-80"
      }`}
    >
      {/* 缩略图：严格 16:9（视频原始比例），视频首帧 + 状态标签 + 时长 */}
      <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-lg bg-gray-100">
        <video
          src={api.getVideoStreamUrl(file.id)}
          preload="metadata"
          muted
          className="h-full w-full object-cover"
        />
        <div className="absolute left-1.5 top-1.5">
          <StatusTag status={file.current_status ?? "pending"} />
        </div>
        {file.duration != null && (
          <span className="absolute bottom-1 right-1 rounded-sm bg-black/60 px-1 text-[10px] leading-4 tabular-nums text-white">
            {formatDur(file.duration)}
          </span>
        )}
      </div>

      {/* AI 结构化标签：统一色彩系统 —— 物体蓝系 / ⚠️ 警示黄系；无标签用占位符保持版面整齐 */}
      <div className="mt-2.5 flex min-h-[22px] flex-wrap items-center gap-1">
        {tags.length > 0 ? (
          tags.map((t) => (
            <span
              key={t}
              className={`rounded-full px-1.5 py-0.5 text-[11px] font-medium leading-4 ${
                t.startsWith("⚠️")
                  ? "bg-amber-50 text-amber-600"
                  : "bg-blue-50 text-blue-600"
              }`}
            >
              {t}
            </span>
          ))
        ) : (
          <span className="text-[11px] leading-4 text-gray-300">暂无解析标签</span>
        )}
      </div>

      {/* 文件名：视觉重心（加大字号 + 加粗） */}
      <p
        title={file.name}
        className="mt-2 truncate text-left text-sm font-semibold leading-5 text-gray-900"
      >
        {file.name}
      </p>

      {/* 辅助信息：日期（缩小减淡，降低视觉噪音） */}
      <div className="mt-1.5 flex items-center text-[11px] text-gray-400">
        <span>{formatStamp(file.created_at)}</span>
      </div>
    </div>
  );
}

/* ── 状态小标签：绿底白字 / 蓝底白字+Loading / 灰底 ── */
function StatusTag({ status }: { status: string }) {
  if (status === "completed") {
    return (
      <span className="w-fit rounded bg-emerald-500 px-1.5 py-0.5 text-[10px] font-medium leading-4 text-white">已完成</span>
    );
  }
  if (status === "processing") {
    return (
      <span className="inline-flex w-fit items-center gap-1 rounded bg-primary px-1.5 py-0.5 text-[10px] font-medium leading-4 text-white">
        <svg className="h-2.5 w-2.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
          <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
        </svg>
        处理中
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="w-fit rounded bg-red-500 px-1.5 py-0.5 text-[10px] font-medium leading-4 text-white">失败</span>
    );
  }
  return (
    <span className="w-fit rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium leading-4 text-gray-500">待处理</span>
  );
}

/* ── 轻量 Toast（底部居中，自动消失） ── */
function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="pointer-events-none fixed bottom-10 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-gray-900/90 px-4 py-2 text-sm text-white shadow-lg">
      {message}
    </div>
  );
}

/* ── 筛选下拉：「标签」+ 当前值 + 下拉箭头，点击展开选项浮层 ── */
function FilterDropdown({
  label,
  value,
  options,
  onSelect,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  /* 点击外部关闭 */
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 items-center gap-1.5 rounded-lg border border-border-light bg-white px-2.5 text-sm shadow-sm transition-colors hover:border-primary/50"
      >
        <span className="text-xs text-gray-400">{label}</span>
        <span className="font-medium text-gray-700">{value}</span>
        <span className={`text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}>
          <IconChevronDown />
        </span>
      </button>

      {open && (
        <ul className="absolute left-0 top-9 z-30 min-w-full overflow-hidden rounded-lg border border-border-light bg-white py-1 shadow-lg">
          {options.map((o) => (
            <li key={o.value}>
              <button
                onClick={() => {
                  onSelect(o.value);
                  setOpen(false);
                }}
                className={`block w-full whitespace-nowrap px-3 py-1.5 text-left text-sm transition-colors ${
                  o.label === value ? "bg-primary-soft font-medium text-primary" : "text-gray-700 hover:bg-surface"
                }`}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* 时长：00:52（两位分钟） */
function formatDur(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* 时间戳：M/D HH:mm（本地时区，与历史记录卡片一致） */
function formatStamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
