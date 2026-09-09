/* ════════════════════════════════════════════════════════════
   downloads — 应用内下载（pywebview 壳桥接，替代系统浏览器下载）
   背景：WebView2 会把 window.open 下载转交外部浏览器，blob + <a download>
   又被 ALLOW_DOWNLOADS=False 静默取消——两路都不是好体验。
   前端只把「接口路径 + 默认文件名」交给壳（SplashApi.download_file）：
   壳弹 Windows 保存框（记住上次目录）→ 线程内拉本地后端写盘 → 进度经
   get_downloads 轮询回填下载弹窗。纯前端文本（任务日志）走 save_text_file。
   浏览器 dev（无 pywebview）回落浏览器原生 blob 下载。
   ════════════════════════════════════════════════════════════ */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { downloadFile as browserSave } from "../services/api";

export interface DownloadJobView {
  id: number;
  name: string;
  path: string;
  status: string;      // 下载中 / 已完成 / 失败 / 已取消（与壳侧 downloads.py 对齐）
  total: number;
  done: number;
  error: string;
  local?: boolean;     // 前端合成任务（文本导出，不经壳 job 队列）
}

interface ShellDownloadApi {
  download_file?: (name: string, path: string, method?: string, body?: unknown) => Promise<{ id: number }>;
  get_downloads?: () => Promise<{ jobs: DownloadJobView[] }>;
  download_retry?: (id: number) => Promise<{ id: number }>;
  download_clear?: (id: number) => Promise<void>;
  save_text_file?: (name: string, content: string) => Promise<{ ok: boolean; msg: string; path?: string; cancelled?: boolean }>;
  open_file_dir?: (path: string) => Promise<{ ok: boolean; msg: string }>;
}
const shell = () => window.pywebview?.api as ShellDownloadApi | undefined;

interface DownloaderCtx {
  jobs: DownloadJobView[];
  activeCount: number;
  open: boolean;
  setOpen: (v: boolean) => void;
  downloadFile: (name: string, apiPath: string, opts?: { method?: string; body?: unknown }) => void;
  downloadText: (name: string, content: string) => void;
  retry: (id: number) => void;
  clear: (id: number) => void;
  openDir: (path: string) => void;
}

const Ctx = createContext<DownloaderCtx | null>(null);

export function useDownloader(): DownloaderCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDownloader 必须在 <DownloadProvider> 内使用");
  return ctx;
}

export function DownloadProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<DownloadJobView[]>([]);
  const [open, setOpen] = useState(false);
  const jobsRef = useRef<DownloadJobView[]>([]);
  jobsRef.current = jobs;
  const hasBridge = !!shell()?.get_downloads;

  const refresh = useCallback(async () => {
    if (!hasBridge) return;
    try {
      const r = await shell()?.get_downloads?.();
      if (r) setJobs((prev) => [...(r.jobs ?? []), ...prev.filter((j) => j.local)]);
    } catch { /* 桥瞬时失败忽略，下轮再取 */ }
  }, [hasBridge]);

  // 轮询回填进度：有活动任务或弹窗打开时 500ms；空闲时空转跳过（一次快照开销极低）
  useEffect(() => {
    const iv = setInterval(() => {
      if (!hasBridge) return;
      if (!open && !jobsRef.current.some((j) => j.status === "下载中")) return;
      void refresh();
    }, 500);
    return () => clearInterval(iv);
  }, [hasBridge, open, refresh]);

  const downloadFile = useCallback((name: string, apiPath: string,
                                    opts?: { method?: string; body?: unknown }) => {
    const s = shell();
    if (s?.download_file) {
      s.download_file(name, apiPath, opts?.method ?? "GET", opts?.body)
        .then(() => refresh()).catch(() => {});
      return;
    }
    // 浏览器 dev 回落：fetch → blob → 浏览器原生保存
    fetch(apiPath, {
      method: opts?.method ?? "GET",
      headers: opts?.body != null ? { "Content-Type": "application/json" } : undefined,
      body: opts?.body != null ? JSON.stringify(opts.body) : undefined,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        browserSave(await res.blob(), name);
      })
      .catch((e) => alert(`下载失败（${e?.message ?? e}）`));
  }, [refresh]);

  const downloadText = useCallback((name: string, content: string) => {
    const s = shell();
    if (!s?.save_text_file) {
      browserSave(new Blob([content], { type: "text/plain;charset=utf-8" }), name);
      return;
    }
    const localId = -Date.now();
    setJobs((prev) => [{ id: localId, name, path: "", status: "下载中", total: 0, done: 0, error: "", local: true }, ...prev]);
    s.save_text_file(name, content)
      .then((r) => setJobs((prev) => prev.map((j) => j.id === localId
        ? { ...j, status: r.ok ? "已完成" : (r.cancelled ? "已取消" : "失败"), path: r.path ?? "", error: r.msg }
        : j)))
      .catch(() => setJobs((prev) => prev.map((j) => j.id === localId ? { ...j, status: "失败", error: "桌面壳不可用" } : j)));
  }, []);

  const retry = useCallback((id: number) => {
    shell()?.download_retry?.(id).then(() => refresh()).catch(() => {});
  }, [refresh]);

  const clear = useCallback((id: number) => {
    setJobs((prev) => {
      const job = prev.find((j) => j.id === id);
      if (job?.local) return prev.filter((j) => j.id !== id);   // 本地合成任务直接移除
      if (job) shell()?.download_clear?.(id);
      return prev.filter((j) => j.id !== id);
    });
  }, []);

  const openDir = useCallback((path: string) => {
    shell()?.open_file_dir?.(path).catch(() => {});
  }, []);

  const value = useMemo<DownloaderCtx>(() => ({
    jobs,
    activeCount: jobs.filter((j) => j.status === "下载中").length,
    open,
    setOpen,
    downloadFile,
    downloadText,
    retry,
    clear,
    openDir,
  }), [jobs, open, downloadFile, retry, clear, downloadText, openDir]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
