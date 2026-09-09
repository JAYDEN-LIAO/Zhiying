/* ════════════════════════════════════════════════════════════
   AboutDialog — 「关于」弹窗（TitleBar 右上角入口）
   展示：渐变 Hero（logo + 产品名 + 型号/版本徽章）+
   检查升级/用户手册按钮 + 状态行（左：检查升级状态/结果，
   右：服务截止时间）+ 版权底栏。关闭方式：点遮罩（无 × 按钮）。
   - 当前版本来自后端 /health（core/version.py 唯一来源）；
   - 检查升级/服务截止时间走 pywebview 壳（软件管家模式 2 / license.dat），
     开发态（licensed=false）检查升级置灰、服务截止时间显示「—」；
   - 检查升级状态三态：检查更新中… / 当前已是最新版本 / 软件管家有新版可升级！
     （失败时展示壳返回的具体原因）；
   - 升级检查/下载由软件管家自带 UI 完成，客户端只等待其返回。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/* 壳桥接口（局部断言，避免 declare global 与 TitleBar 的声明合并冲突） */
interface AboutApi {
  get_about_info?: () => Promise<{ product_model: string; licensed: boolean; expired_date: string | null }>;
  check_upgrade?: (version: string) => Promise<{ ok: boolean; msg: string; has_update?: boolean }>;
  open_manual?: () => Promise<{ ok: boolean; msg: string }>;
}
const aboutApi = () => window.pywebview?.api as AboutApi | undefined;

/* 检查升级状态：checking=进行中 / latest=已是最新 / update=有新版 / error=失败原因 */
type UpgradeStatus = { kind: "checking" | "latest" | "update" | "error"; text: string };

interface Props {
  open: boolean;
  onClose: () => void;
  version: string | null;
}

export function AboutDialog({ open, onClose, version }: Props) {
  const [about, setAbout] = useState<{ product_model: string; licensed: boolean; expired_date: string | null } | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [status, setStatus] = useState<UpgradeStatus | null>(null);

  useEffect(() => {
    if (!open) return;
    setStatus(null);
    aboutApi()?.get_about_info?.().then(setAbout).catch(() => setAbout(null));
  }, [open]);

  if (!open) return null;

  const licensed = about?.licensed ?? false;

  const onCheckUpgrade = async () => {
    if (upgrading || !licensed) return;
    setUpgrading(true);
    setStatus({ kind: "checking", text: "检查更新中..." });
    try {
      const r = await aboutApi()?.check_upgrade?.(version ?? "");
      if (!r) setStatus({ kind: "error", text: "桌面壳不可用（浏览器开发态）" });
      else if (r.has_update) setStatus({ kind: "update", text: "软件管家有新版可升级！" });
      else if (r.ok) setStatus({ kind: "latest", text: "当前已是最新版本" });
      else setStatus({ kind: "error", text: r.msg || "检查升级失败" });
    } catch {
      setStatus({ kind: "error", text: "检查升级失败" });
    }
    setUpgrading(false);
  };

  const onOpenManual = async () => {
    try {
      const r = await aboutApi()?.open_manual?.();
      if (r && !r.ok) setStatus({ kind: "error", text: r.msg || "打开手册失败" });
    } catch {
      setStatus({ kind: "error", text: "打开手册失败" });
    }
  };

  return createPortal(
    <div className="g-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="g-modal about-modal" style={{ width: 800, padding: 0 }}>
        {/* Hero：渐变底 + logo + 产品名 + 型号/版本徽章 */}
        <div className="about-hero">
          <img src="/zhiying_logo_512.png" alt="logo" className="about-logo" />
          <div className="about-name">视频快速智能检索平台</div>
          <div className="about-pills">
            <span className="about-pill">产品型号 · {about?.product_model ?? "A5300"}</span>
            <span className="about-pill">当前版本 · {version ?? "—"}</span>
          </div>
        </div>

        {/* 正文：操作按钮 + 状态行（左状态/右服务截止时间） */}
        <div className="about-body">
          <div className="about-actions">
            <button
              className="g-btn g-btn-primary about-btn"
              disabled={!licensed || upgrading}
              onClick={() => void onCheckUpgrade()}
              title={licensed ? undefined : "开发态不可用（仅封装版支持检查升级）"}
            >
              {upgrading ? "检查更新中..." : "检查升级"}
            </button>
            <button className="g-btn about-btn" onClick={() => void onOpenManual()}>
              用户手册
            </button>
          </div>

          {/* 状态行：左=检查升级状态/结果（等高占位防跳动），右=服务截止时间 */}
          <div className="about-status">
            <span className={`about-status-msg${status ? ` about-status-${status.kind}` : ""}`}>
              {status?.text ?? ""}
            </span>
            <span className="about-expire">
              服务截止时间：{licensed ? (about?.expired_date ?? "—") : "—"}
            </span>
          </div>
        </div>

        {/* 版权底栏（分割线独立于正文） */}
        <div className="about-footer">
          ©2009-2026南京拓界信息技术有限公司&emsp;热线电话：025-84600004
        </div>
      </div>
    </div>,
    document.body,
  );
}
