import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { YunzhiProvider } from "./platform/YunzhiProvider";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <YunzhiProvider>
      <App />
    </YunzhiProvider>
  </React.StrictMode>
);

// 启动毛玻璃占位（index.html #boot）：等 React 真正挂载一帧后淡出移除，避免白屏/闪跳
requestAnimationFrame(() => {
  const boot = document.getElementById("boot");
  if (boot) {
    boot.style.opacity = "0";
    setTimeout(() => boot.remove(), 320);
  }
});
