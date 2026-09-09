import { useRef, useState, type ReactNode } from "react";

/* ════════════════════════════════════════════════════════════
   SplitPane — 双栏可拖拽分割容器（行/列方向）
   拖动中间分隔条调整比例；分隔条默认隐形，hover 显蓝色细线
   ════════════════════════════════════════════════════════════ */

export function SplitPane({
  direction,
  initial,
  min,
  max,
  first,
  second,
  className = "",
}: {
  direction: "row" | "col";
  initial: number; // 初始百分比（first 占比）
  min: number;
  max: number;
  first: ReactNode;
  second: ReactNode;
  className?: string;
}) {
  const [pct, setPct] = useState(initial);
  const ref = useRef<HTMLDivElement>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const onMove = (ev: PointerEvent) => {
      const p =
        direction === "row"
          ? ((ev.clientX - rect.left) / rect.width) * 100
          : ((ev.clientY - rect.top) / rect.height) * 100;
      setPct(Math.min(max, Math.max(min, p)));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    document.body.style.cursor = direction === "row" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div ref={ref} className={`flex ${direction === "row" ? "flex-row" : "flex-col"} ${className}`}>
      <div className="min-h-0 min-w-0" style={direction === "row" ? { width: `${pct}%` } : { height: `${pct}%` }}>
        {first}
      </div>
      {/* 分隔条（兼作面板间距） */}
      <div
        onPointerDown={onPointerDown}
        className={`group relative z-10 shrink-0 ${direction === "row" ? "w-3 cursor-col-resize" : "h-3 cursor-row-resize"}`}
      >
        <div
          className={`absolute rounded-full bg-gray-300/0 transition-colors group-hover:bg-primary ${
            direction === "row"
              ? "inset-y-3 left-1/2 w-0.5 -translate-x-1/2"
              : "inset-x-3 top-1/2 h-0.5 -translate-y-1/2"
          }`}
        />
      </div>
      <div className="min-h-0 min-w-0 flex-1">{second}</div>
    </div>
  );
}
