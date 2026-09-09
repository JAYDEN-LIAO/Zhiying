import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  onClick: () => void;
}

interface ContextMenuState {
  x: number;
  y: number;
  items: MenuItem[];
}

/* 右键菜单状态钩子：在触发元素上 onContextMenu={openMenu} 即可 */
export function useContextMenu() {
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const open = (e: ReactMouseEvent, items: MenuItem[]) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, items });
  };
  const close = () => setMenu(null);
  return { menu, open, close };
}

export function ContextMenu({ menu, onClose }: { menu: ContextMenuState; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const scroll = () => onClose();
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    window.addEventListener("scroll", scroll, true);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [onClose]);

  /* 视口边缘防溢出 */
  const x = Math.min(menu.x, window.innerWidth - 180);
  const y = Math.min(menu.y, window.innerHeight - menu.items.length * 32 - 12);

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[160px] rounded-lg border border-border-light bg-card-bg p-1 shadow-lg"
      style={{ left: x, top: y }}
    >
      {menu.items.map((i) => (
        <button
          key={i.label}
          onClick={() => {
            i.onClick();
            onClose();
          }}
          className={`flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors ${
            i.danger ? "text-red-500 hover:bg-red-50" : "text-gray-700 hover:bg-primary-soft"
          }`}
        >
          {i.icon}
          {i.label}
        </button>
      ))}
    </div>
  );
}
