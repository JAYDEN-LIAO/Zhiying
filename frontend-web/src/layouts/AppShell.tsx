import { createContext, useContext, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { TopNav } from "./TopNav";
import { HistoryDrawer } from "../components/common/HistoryDrawer";
import { FilePickerModal } from "../components/common/FilePickerModal";

/* ════════════════════════════════════════════════════════════
   AppShell — 全局布局
   顶部导航（双 Tab + 右侧功能区） / 路由出口
   常驻：历史记录抽屉（右侧滑出，圆角） +
   文件库单选弹窗（TopNav「更换视频」入口）
   ════════════════════════════════════════════════════════════ */

/* 历史记录抽屉全局打开钩子（子页面空状态入口用） */
const HistoryDrawerCtx = createContext<{ openDrawer: () => void }>({ openDrawer: () => {} });
export const useHistoryDrawer = () => useContext(HistoryDrawerCtx);

export function AppShell() {
  const navigate = useNavigate();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  return (
    <HistoryDrawerCtx.Provider value={{ openDrawer: () => setHistoryOpen(true) }}>
      <div className="flex h-dvh flex-col bg-gradient-to-bl from-[#eaf1ff] via-[#f5f8ff] to-[#dbe7ff]">
        <TopNav
          onOpenHistory={() => setHistoryOpen(true)}
          onOpenPicker={() => setPickerOpen(true)}
        />
        <main className="min-h-0 flex-1">
          <Outlet />
        </main>
        <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
      {/* TopNav「更换视频」：文件库单选 → 切换主界面视频源 */}
      <FilePickerModal
        mode="single"
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={(r) => {
          const id = r.videoIds[0];
          if (id) navigate(`/?video=${id}`);
        }}
      />
      </div>
    </HistoryDrawerCtx.Provider>
  );
}
