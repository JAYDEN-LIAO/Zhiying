/* 任务/文件状态徽章（原桌面端 STATUS_META 的精简版，样式走 Tailwind） */
const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待处理", cls: "bg-gray-100 text-gray-500", pulse: true },
  queued: { label: "排队中", cls: "bg-amber-50 text-amber-600", pulse: true },
  processing: { label: "处理中", cls: "bg-primary-soft text-primary", pulse: true },
  completed: { label: "已完成", cls: "bg-emerald-50 text-emerald-600" },
  failed: { label: "失败", cls: "bg-red-50 text-red-500" },
};

export function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.pending;
  return (
    <span className={`inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium ${m.cls}`}>
      {m.pulse && <span className="mr-1 h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {m.label}
    </span>
  );
}
