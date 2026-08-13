/* ════════════════════════════════════════════════════════════
   SplitPane — 可拖拽分栏（v0.34，自智影 v2 demo SplitPane.jsx 移植到 React）
   props:
     direction  'row' 左右 | 'col' 上下
     initial    第一面板初始占比 %（默认 50）
     min / max  拖拽范围（默认 12 / 88）
     handleSize 手柄宽/高 px（默认 6）
     className  附加类名
     children   [第一面板, 第二面板]（数组）
   CSS 见 index.css .split-pane 系列
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  direction: "row" | "col";
  initial?: number;
  min?: number;
  max?: number;
  handleSize?: number;
  className?: string;
  children: [ReactNode, ReactNode];
}

export function SplitPane({
  direction,
  initial = 50,
  min = 12,
  max = 88,
  handleSize = 6,
  className,
  children,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState(initial);
  // 拖拽进行中标记：卸载时兜底清理（防 pointercancel/组件销毁后 body 光标/userSelect 卡死）
  const draggingRef = useRef<{ cleanup: () => void } | null>(null);

  useEffect(() => {
    return () => draggingRef.current?.cleanup();
  }, []);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    container.classList.add("resizing");
    document.body.style.cursor = direction === "row" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: PointerEvent) => {
      let pct: number;
      if (direction === "row") pct = ((ev.clientX - rect.left) / rect.width) * 100;
      else pct = ((ev.clientY - rect.top) / rect.height) * 100;
      setRatio(Math.min(max, Math.max(min, pct)));
    };
    const end = () => {
      draggingRef.current = null;
      container.classList.remove("resizing");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
    };
    draggingRef.current = { cleanup: end };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  };

  return (
    <div ref={containerRef} className={`split-pane split-${direction}${className ? ` ${className}` : ""}`}>
      <div
        className="split-pane-panel"
        style={direction === "row" ? { width: `${ratio}%` } : { height: `${ratio}%` }}
      >
        {children[0]}
      </div>
      <div
        className={`split-pane-handle split-handle-${direction}`}
        style={direction === "row" ? { width: handleSize } : { height: handleSize }}
        onPointerDown={onPointerDown}
      />
      <div className="split-pane-panel split-pane-rest">{children[1]}</div>
    </div>
  );
}
