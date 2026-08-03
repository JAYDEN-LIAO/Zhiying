/* ════════════════════════════════════════════════════════════
   SettingsPage — 系统设置
   三个区块（都是真实生效的）：
    1. 存储路径：新上传 / 转码 / 导出使用的目录（默认沿用现有配置）
    2. API 服务：DashScope / DeepSeek 的 端点 + 模型名 + 密钥
   保存即写入 data/settings.json 并运行时生效（无需重启）。
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { SettingsData, SettingsUpdate } from "../types";

const PROVIDER_IDS = ["dashscope", "deepseek"] as const;
const PROVIDER_HINT: Record<string, string> = {
  dashscope: "画面描述（caption，vlm_llm 模式）",
  deepseek: "摘要生成（summary，vlm_llm 模式）",
};

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);

  // 编辑态
  const [apiKeyEdit, setApiKeyEdit] = useState<Record<string, string>>({});
  const [providerEdit, setProviderEdit] = useState<Record<string, { base_url: string; model: string }>>({});
  const [storageEdit, setStorageEdit] = useState<{ video_dir: string; artifact_dir: string }>({
    video_dir: "",
    artifact_dir: "",
  });

  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const load = () => {
    api.getSettings().then((data) => {
      setSettings(data);
      setProviderEdit({
        dashscope: { base_url: data.providers?.dashscope?.base_url ?? "", model: data.providers?.dashscope?.model ?? "" },
        deepseek: { base_url: data.providers?.deepseek?.base_url ?? "", model: data.providers?.deepseek?.model ?? "" },
      });
      setStorageEdit({
        video_dir: data.storage?.video_dir ?? "",
        artifact_dir: data.storage?.artifact_dir ?? "",
      });
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const flash = (type: "ok" | "err", text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 4000);
  };

  const saveKeys = async () => {
    setSaving("keys"); setMsg(null);
    try {
      const payload: SettingsUpdate = { api_keys: apiKeyEdit, providers: providerEdit };
      await api.updateSettings(payload);
      setApiKeyEdit({});
      load();
      flash("ok", "API 服务已保存，运行时即时生效");
    } catch (e) { flash("err", e instanceof Error ? e.message : "保存失败"); }
    finally { setSaving(null); }
  };

  const saveStorage = async () => {
    setSaving("storage"); setMsg(null);
    try {
      await api.updateSettings({ storage: storageEdit });
      load();
      flash("ok", "存储路径已保存：新上传立即生效，转码/导出亦将使用新目录");
    } catch (e) { flash("err", e instanceof Error ? e.message : "保存失败"); }
    finally { setSaving(null); }
  };

  const inputCls = "w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-blue-300";
  const labelCls = "text-xs text-gray-500 mb-1 block";

  return (
    <div className="flex-1 flex flex-col pt-[80px] pl-8 pr-4 pb-4">
      <div className="flex gap-4 items-start">
        {/* ── 存储路径 ── */}
        <div className="flex-1 bg-[var(--color-white)] rounded-[var(--radius-lg)] p-6 border border-[var(--color-border-light)] shadow-[var(--shadow-sm)]">
          <h3 className="font-semibold text-gray-900 text-sm mb-1">存储路径</h3>
          <p className="text-[10px] text-gray-400 mb-4">新上传的视频与处理制品存放目录（默认沿用现有配置，保存后运行时生效）</p>
          <div className="space-y-4">
            <div>
              <label className={labelCls}>视频目录</label>
              <input type="text" value={storageEdit.video_dir} placeholder="data/videos"
                onChange={(e) => setStorageEdit((p) => ({ ...p, video_dir: e.target.value }))}
                className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>制品目录</label>
              <input type="text" value={storageEdit.artifact_dir} placeholder="data/artifacts"
                onChange={(e) => setStorageEdit((p) => ({ ...p, artifact_dir: e.target.value }))}
                className={inputCls} />
            </div>
            <button onClick={saveStorage} disabled={saving === "storage"}
              className="px-4 py-2 text-xs font-medium bg-[#1d4ed8] text-white rounded-lg hover:bg-blue-600 disabled:opacity-40 transition-colors">
              {saving === "storage" ? "保存中..." : "保存路径"}
            </button>
          </div>
        </div>

        {/* ── API 密钥与服务 ── */}
        <div className="flex-1 bg-[var(--color-white)] rounded-[var(--radius-lg)] p-6 border border-[var(--color-border-light)] shadow-[var(--shadow-sm)]">
          <h3 className="font-semibold text-gray-900 text-sm mb-1">API 密钥与服务</h3>
          <p className="text-[10px] text-gray-400 mb-4">摘要 vlm_llm 模式使用；端点 + 模型名 + 密钥均可改（密钥留空则保持不变）</p>
          {loading ? (
            <div className="animate-pulse space-y-3">
              <div className="h-10 bg-gray-100 rounded" /><div className="h-10 bg-gray-100 rounded" />
            </div>
          ) : (
            <div className="space-y-5">
              {PROVIDER_IDS.map((pid) => {
                const keyInfo = settings?.api_keys?.[pid];
                const edit = providerEdit[pid] ?? { base_url: "", model: "" };
                return (
                  <div key={pid} className="border border-gray-100 rounded-lg p-3 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-gray-700">{keyInfo?.label ?? pid}</span>
                      <span className="flex items-center gap-1.5 text-[10px] text-gray-400">
                        <span className={`inline-block w-2 h-2 rounded-full ${keyInfo?.configured ? "bg-green-400" : "bg-gray-300"}`} />
                        {keyInfo?.configured ? `已配置 · ${keyInfo.masked_value}` : "密钥未配置"}
                      </span>
                    </div>
                    <div>
                      <label className={labelCls}>接口地址 (Base URL)</label>
                      <input type="text" value={edit.base_url} placeholder="https://..."
                        onChange={(e) => setProviderEdit((p) => ({ ...p, [pid]: { ...p[pid], base_url: e.target.value } }))}
                        className={inputCls} />
                    </div>
                    <div>
                      <label className={labelCls}>模型名</label>
                      <input type="text" value={edit.model} placeholder={pid === "dashscope" ? "qwen-vl-max" : "deepseek-chat"}
                        onChange={(e) => setProviderEdit((p) => ({ ...p, [pid]: { ...p[pid], model: e.target.value } }))}
                        className={inputCls} />
                    </div>
                    <div>
                      <label className={labelCls}>API 密钥（{PROVIDER_HINT[pid]}）</label>
                      <input type="password" placeholder={keyInfo?.configured ? "••••••••（留空保持不变）" : "未配置"}
                        value={apiKeyEdit[pid] ?? ""}
                        onChange={(e) => setApiKeyEdit((p) => ({ ...p, [pid]: e.target.value }))}
                        className={inputCls} />
                    </div>
                  </div>
                );
              })}
              <button onClick={saveKeys} disabled={saving === "keys"}
                className="px-4 py-2 text-xs font-medium bg-[#1d4ed8] text-white rounded-lg hover:bg-blue-600 disabled:opacity-40 transition-colors">
                {saving === "keys" ? "保存中..." : "保存密钥与服务"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 全局提示 */}
      {msg && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2 text-xs rounded-lg shadow-lg text-white z-50 ${msg.type === "ok" ? "bg-green-600" : "bg-red-600"}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
