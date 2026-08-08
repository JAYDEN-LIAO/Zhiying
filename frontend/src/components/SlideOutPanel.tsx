/* ════════════════════════════════════════════════════════════
   SlideOutPanel — generic slide-out drawer for params/history
   （v0.28：从右侧滑出、高度低于 header，适配云智嵌入场景）
   ════════════════════════════════════════════════════════════ */

import { useRef, useEffect } from "react";

interface SlideOutPanelProps {
  open: boolean;
  width: number;
  children: React.ReactNode;
}

/**
 * Animated slide-out drawer from the right, below the 52px header.
 * Positioning/shadows in index.css (.slide-panel / .slide-panel-inner).
 */
export function SlideOutPanel({ open, width, children }: SlideOutPanelProps) {
  const innerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && innerRef.current) {
      innerRef.current.focus();
    }
  }, [open]);

  return (
    <div
      className="slide-panel"
      style={{
        right: 0,
        top: 52,
        width: open ? width : 0,
        height: "calc(100% - 52px)",
        borderColor: open ? "rgba(203, 213, 225, 0.8)" : "transparent",
        boxShadow: open ? "-4px 0 24px rgba(0,0,0,0.3)" : "none",
        transition: "width 500ms cubic-bezier(0.4, 0, 0.2, 1)",
      }}
    >
      <div
        ref={innerRef}
        tabIndex={-1}
        className="slide-panel-inner"
        style={{
          right: open ? 0 : -width,
          width,
          transition: "right 500ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
