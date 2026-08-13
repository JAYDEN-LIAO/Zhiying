/* ════════════════════════════════════════════════════════════
   SystemMonitor — 侧栏底部真机系统监控（v0.34 桌面重构 · 修复版）
   demo 风格：每项 = 图标+标签+数值（左） + 迷你柱状图（右，历史缓冲）。
   CPU/内存/GPU 走 get_system_stats()（psutil+nvidia-smi），网络全宽迷你图。
   ⚠️ 时序修复：pywebview 的 bridge 是页面加载后异步注入的，React effect
   挂载时 window.pywebview 往往还不存在 → 必须等 pywebviewready 事件 +
   轮询重试，就绪后才开始 3s 轮询。浏览器 dev 无 pywebview → 不渲染。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState } from "react";
import { IconCpu, IconRam, IconGpu, IconNet } from "./icons";

interface SysStats {
  cpu?: { percent: number } | null;
  memory?: { percent: number; used_gb: number; total_gb: number } | null;
  gpu?: { name: string; percent: number; used_mb: number; total_mb: number; temp_c: number } | null;
  net?: { down_bps: number; up_bps: number } | null;
  ts?: number;
}

const HISTORY = 8;

function fmtBps(bps: number): string {
  if (bps >= 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
  return `${bps} B/s`;
}

/** 迷你柱状图：用最近 N 个采样值生成柱高（带末柱高亮） */
function MiniBars({ values, color, wide }: { values: number[]; color: string; wide?: boolean }) {
  const max = Math.max(8, ...values.map((v) => v || 0));
  return (
    <div className={"mini-bars" + (wide ? " wide" : "")}>
      {values.map((v, i) => (
        <i
          key={i}
          style={{
            height: `${Math.max(6, ((v || 0) / max) * 100)}%`,
            background: i === values.length - 1 ? color : `${color}99`,
            opacity: i === values.length - 1 ? 1 : 0.75,
          }}
        />
      ))}
    </div>
  );
}

export function SystemMonitor() {
  const [stats, setStats] = useState<SysStats | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  // 历史缓冲（迷你柱状图数据源）
  const cpuHist = useRef<number[]>([]);
  const memHist = useRef<number[]>([]);
  const gpuHist = useRef<number[]>([]);
  const netHist = useRef<number[]>([]);
  const [, force] = useState(0);

  useEffect(() => {
    let alive = true;
    let started = false; // 防 pywebviewready + 立即尝试 + 重试轮询三路重复启动
    let retry: number;
    let timer: number;

    const start = () => {
      if (started) return;
      const api = window.pywebview?.api as { get_system_stats?: () => Promise<SysStats> } | undefined;
      if (!api?.get_system_stats) {
        // bridge 未注入 → 等 pywebviewready 或轮询重试
        retry = window.setTimeout(start, 300);
        return;
      }
      started = true;
      const tick = async () => {
        if (!alive) return;
        try {
          const s = await api.get_system_stats!();
          if (!alive) return;
          setStats(s);
          const push = (arr: number[], v: number) => { arr.push(v); if (arr.length > HISTORY) arr.shift(); };
          if (s.cpu != null) push(cpuHist.current, s.cpu.percent);
          if (s.memory != null) push(memHist.current, s.memory.percent);
          if (s.gpu != null) push(gpuHist.current, s.gpu.percent);
          if (s.net != null) push(netHist.current, s.net.down_bps);
          force((n) => n + 1);
        } catch {
          /* 单次失败不打断 */
        }
        if (alive) timer = window.setTimeout(tick, 3000);
      };
      tick();
    };

    window.addEventListener("pywebviewready", start);
    start(); // 立即尝试（可能已注入）
    return () => {
      alive = false;
      window.removeEventListener("pywebviewready", start);
      clearTimeout(retry);
      clearTimeout(timer);
    };
  }, []);

  if (!stats || collapsed) return null;

  return (
    <div className="sysmon">
      {stats.cpu != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#4f7cff" }}><IconCpu />CPU <b>{stats.cpu.percent}%</b></span>
            <MiniBars values={cpuHist.current} color="#4f7cff" />
          </div>
        </div>
      )}

      {stats.memory != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#10b981" }}><IconRam />内存 <b>{stats.memory.percent}%</b></span>
            <MiniBars values={memHist.current} color="#10b981" />
          </div>
          <div className="sysmon-sub">{stats.memory.used_gb} GB / {stats.memory.total_gb} GB</div>
        </div>
      )}

      {stats.gpu != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#8b5cf6" }}><IconGpu />GPU <b>{stats.gpu.percent}%</b></span>
            <MiniBars values={gpuHist.current} color="#8b5cf6" />
          </div>
          <div className="sysmon-sub">
            {(stats.gpu.used_mb / 1024).toFixed(1)} / {(stats.gpu.total_mb / 1024).toFixed(1)} GB · {stats.gpu.temp_c}°C
          </div>
        </div>
      )}

      {stats.net != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#f59e0b" }}><IconNet />网络</span>
            <span className="sysmon-net-val">↓ {fmtBps(stats.net.down_bps)}　↑ {fmtBps(stats.net.up_bps)}</span>
          </div>
          <MiniBars values={netHist.current} color="#f59e0b" wide />
        </div>
      )}

      <div className="sysmon-fold">
        <button title="折叠" onClick={() => setCollapsed(true)}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4 14 12 22 20 14" /><polyline points="4 4 12 12 20 4" />
          </svg>
        </button>
      </div>
    </div>
  );
}
