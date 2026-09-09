/* ════════════════════════════════════════════════════════════
   Router — Web 端路由（单页双视图，全局搜索模块已移除）
   /            智能解析
     无参数     已处理视频列表（网格）
     ?video=id  解析详情工作台（query: &t=<秒>&refresh=<ts>）
   ════════════════════════════════════════════════════════════ */

import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./layouts/AppShell";
import { ParsePage } from "./pages/ParsePage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <ParsePage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
