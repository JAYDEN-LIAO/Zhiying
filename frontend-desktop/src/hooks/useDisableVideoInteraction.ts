import { useEffect } from "react";

/* 弹窗打开期间，禁用页面中所有 <video> 元素的 pointer-events。
   目的：背景视频保持【可见】（pointer-events 不影响渲染），但完全不可被点击，
   从而保证点击弹窗（含 ✕ 关闭按钮）绝不会与背景视频产生交互。
   弹窗卸载后自动恢复。用 querySelectorAll 覆盖所有 video，避免漏选。 */
export function useDisableVideoInteraction() {
  useEffect(() => {
    const videos = Array.from(document.querySelectorAll("video"));
    if (videos.length === 0) return;
    const prev = videos.map((v) => v.style.pointerEvents);
    videos.forEach((v) => { v.style.pointerEvents = "none"; });
    return () => {
      videos.forEach((v, i) => { v.style.pointerEvents = prev[i]; });
    };
  }, []);
}