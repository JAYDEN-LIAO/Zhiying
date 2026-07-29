/* ════════════════════════════════════════════════════════════
   SlideOutPanel — generic slide-out container for params/history
   ════════════════════════════════════════════════════════════ */

import { useRef, useEffect } from "react";

interface SlideOutPanelProps {
  open: boolean;
  width: number;
  children: React.ReactNode;
}

/**
 * Animated slide-out panel from the left (behind sidebar).
 * Uses CSS transitions from index.css (.slide-panel / .slide-panel-inner).
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
        left: 32,
        width: open ? width : 0,
        height: "100%",
        borderColor: open ? "rgba(203, 213, 225, 0.8)" : "transparent",
        boxShadow: open ? "4px 0 24px rgba(0,0,0,0.3)" : "none",
        transition: "width 500ms cubic-bezier(0.4, 0, 0.2, 1)",
      }}
    >
      <div
        ref={innerRef}
        tabIndex={-1}
        className="slide-panel-inner"
        style={{
          left: open ? 0 : -width,
          width,
          transition: "left 500ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
