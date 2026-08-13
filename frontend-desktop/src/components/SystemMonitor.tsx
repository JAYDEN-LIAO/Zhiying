/* ════════════════════════════════════════════════════════════
   SystemMonitor — 侧栏底部真机系统监控（v0.34）
   每 3s 轮询桌面壳 pywebview.api.get_system_stats()（psutil + nvidia-smi）。
   浏览器 dev 无 pywebview → 不渲染。纯前端 + 桌面壳，不动后端。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useState } from "react";
import { IconCpu, IconRam, IconGpu, IconNet } from "./icons";

interface SysStats {
  cpu?: { percent: number } | null;
  memory?: { percent: number; used_gb: number; total_gb: number } | null;
  gpu?: { name: string; percent: number; used_mb: number; total_mb: number; temp_c: number } | null;
  net?: { down_bps: number; up_bps: number } | null;
  ts?: number;
}

function fmtBps(bps: number): string {
  if (bps >= 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
  return `${bps} B/s`;
}

function SysItem({ icon, label, pct, val, color, sub }: {
  icon: React.ReactNode; label: string; pct: number; val: string; color: string; sub?: string;
}) {
  return (
    <div>
      <div className="sysmon-item">
        <span className="sysmon-label" style={{ color }}>{icon}{label}</span>
        <span className="sysmon-bar">
          <span className="sysmon-fill" style={{ width: `${Math.max(2, pct)}%`, background: color }} />
        </span>
        <span className="sysmon-val">{val}</span>
      </div>
      {sub && <div className="sysmon-sub" style={{ paddingLeft: 64 }}>{sub}</div>}
    </div>
  );
}

export function SystemMonitor() {
  const [stats, setStats] = useState<SysStats | null>(null);

  useEffect(() => {
    const api = window.pywebview?.api as { get_system_stats?: () => Promise<SysStats> } | undefined;
    if (!api?.get_system_stats) return; // 浏览器 dev 无 pywebview → 不渲染
    let alive = true;
    const tick = async () => {
      try {
        const s = await api.get_system_stats!();
        if (alive) setStats(s);
      } catch {
        /* 容错：单次失败不打断轮询 */
      }
      if (alive) setTimeout(tick, 3000);
    };
    tick();
    return () => { alive = false; };
  }, []);

  if (!stats) return null;

  return (
    <div className="sysmon">
      {stats.cpu != null && (
        <SysItem icon={<IconCpu />} label="CPU" pct={stats.cpu.percent} val={`${stats.cpu.percent}%`} color="#4f7cff" />
      )}
      {stats.memory != null && (
        <SysItem
          icon={<IconRam />} label="内存" pct={stats.memory.percent} val={`${stats.memory.percent}%`}
          color="#10b981" sub={`${stats.memory.used_gb} / ${stats.memory.total_gb} GB`}
        />
      )}
      {stats.gpu != null && (
        <SysItem
          icon={<IconGpu />} label="GPU" pct={stats.gpu.percent} val={`${stats.gpu.percent}%`}
          color="#8b5cf6"
          sub={`${(stats.gpu.used_mb / 1024).toFixed(1)} / ${(stats.gpu.total_mb / 1024).toFixed(1)} GB · ${stats.gpu.temp_c}°C`}
        />
      )}
      {stats.net != null && (
        <div className="sysmon-item">
          <span className="sysmon-label" style={{ color: "#f59e0b" }}><IconNet />网络</span>
          <span className="sysmon-sub" style={{ width: "auto", marginLeft: 8 }}>
            ↓ {fmtBps(stats.net.down_bps)}　↑ {fmtBps(stats.net.up_bps)}
          </span>
        </div>
      )}
    </div>
  );
}
