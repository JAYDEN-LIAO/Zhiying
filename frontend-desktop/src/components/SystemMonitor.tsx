/* ════════════════════════════════════════════════════════════
   SystemMonitor — 侧栏底部真机系统监控（v0.34 桌面重构）
   每项 = 图标+标签+数值（左） + 实时折线图（右，历史缓冲 SVG sparkline）。
   CPU/内存/GPU 走 get_system_stats()（psutil+nvidia-smi），网络全宽折线。
   ⚠️ 时序修复：pywebview bridge 异步注入，等 pywebviewready + 轮询重试 +
   防重复启动守卫，就绪后才开始 3s 轮询。浏览器 dev 无 pywebview → 不渲染。
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

const HISTORY = 16;

function fmtBps(bps: number): string {
  if (bps >= 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
  return `${bps} B/s`;
}

/** 实时折线（SVG）：面积填充 + 折线 + 末端点 */
function SparkLine({ values, color, width, height, max }: {
  values: number[]; color: string; width: number; height: number; max: number;
}) {
  const n = values.length;
  const hi = Math.max(1, max);
  const pts = values.map((v, i) => {
    const x = n <= 1 ? 0 : (i / (n - 1)) * width;
    const y = height - Math.max(0, Math.min(1, (v || 0) / hi)) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = pts.join(" ");
  const area = n ? `0,${height} ${line} ${width},${height}` : "";
  return (
    <svg width={width} height={height} className="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {area && <polygon points={area} fill={color} opacity="0.14" />}
      {line && <polyline points={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />}
      {n > 0 && <circle cx={width} cy={height - Math.max(0, Math.min(1, (values[n - 1] || 0) / hi)) * height} r="1.8" fill={color} />}
    </svg>
  );
}

export function SystemMonitor() {
  const [stats, setStats] = useState<SysStats | null>(null);

  const cpuHist = useRef<number[]>([]);
  const memHist = useRef<number[]>([]);
  const gpuHist = useRef<number[]>([]);
  const netHist = useRef<number[]>([]);
  const [, force] = useState(0);

  useEffect(() => {
    let alive = true;
    let started = false;
    let retry: number;
    let timer: number;

    const start = () => {
      if (started) return;
      const api = window.pywebview?.api as { get_system_stats?: () => Promise<SysStats> } | undefined;
      if (!api?.get_system_stats) {
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
    start();
    return () => {
      alive = false;
      window.removeEventListener("pywebviewready", start);
      clearTimeout(retry);
      clearTimeout(timer);
    };
  }, []);

  if (!stats) return null;

  return (
    <div className="sysmon">
      {stats.cpu != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#4f7cff" }}><IconCpu />CPU <b>{stats.cpu.percent}%</b></span>
            <SparkLine values={cpuHist.current} color="#4f7cff" width={64} height={18} max={100} />
          </div>
        </div>
      )}

      {stats.memory != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#10b981" }}><IconRam />内存 <b>{stats.memory.percent}%</b></span>
            <SparkLine values={memHist.current} color="#10b981" width={64} height={18} max={100} />
          </div>
          <div className="sysmon-sub">{stats.memory.used_gb} GB / {stats.memory.total_gb} GB</div>
        </div>
      )}

      {stats.gpu != null && (
        <div>
          <div className="sysmon-row">
            <span className="sysmon-l" style={{ color: "#8b5cf6" }}><IconGpu />GPU <b>{stats.gpu.percent}%</b></span>
            <SparkLine values={gpuHist.current} color="#8b5cf6" width={64} height={18} max={100} />
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
          <SparkLine values={netHist.current} color="#f59e0b" width={132} height={16} max={Math.max(10240, ...netHist.current)} />
        </div>
      )}
    </div>
  );
}
