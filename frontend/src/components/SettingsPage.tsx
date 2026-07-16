/* ════════════════════════════════════════════════════════════
   SettingsPage — extracted from Dashboard.tsx
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";


export function SettingsPage() {
  const [apiKeys, setApiKeys] = useState<Record<string, { id: string; label: string; configured: boolean; masked_value: string | null }>>({});
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loadingKeys, setLoadingKeys] = useState(true);

  useEffect(() => {
    api.getSettings()
      .then((data) => { setApiKeys(data.api_keys); setLoadingKeys(false); })
      .catch(() => setLoadingKeys(false));
  }, []);

  const handleSaveKeys = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const data = await api.updateSettings(editValues);
      setApiKeys(data.api_keys);
      setEditValues({});
      setMessage("API 密钥已保存");
      setTimeout(() => setMessage(null), 3000);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col pt-[90px] pl-8 pr-4 pb-4">
      <div className="flex gap-4" style={{ alignItems: 'flex-start' }}>
        <div className="flex-1 card-surface rounded-2xl p-6 border border-gray-200/60 overflow-y-auto">
          <div className="space-y-5">
            <section>
              <h3 className="font-semibold text-gray-900 text-sm mb-3">存储路径</h3>
              <div className="space-y-2">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">视频目录</label>
                  <input type="text" defaultValue="data/videos" className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-blue-300" />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">制品目录</label>
                  <input type="text" defaultValue="data/artifacts" className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-blue-300" />
                </div>
              </div>
            </section>
          </div>
        </div>

        <div className="flex-1 card-surface rounded-2xl p-6 border border-gray-200/60 overflow-y-auto">
          <h3 className="font-semibold text-gray-900 text-sm mb-3">API 密钥</h3>
          {loadingKeys ? (
            <div className="animate-pulse space-y-3">
              <div className="h-10 bg-gray-100 rounded" />
              <div className="h-10 bg-gray-100 rounded" />
            </div>
          ) : (
            <div className="space-y-4">
              {Object.values(apiKeys).map((keyInfo: any) => (
                <div key={keyInfo.id}>
                  <label className="text-xs text-gray-500 mb-1 block">{keyInfo.label}</label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      placeholder={keyInfo.configured ? "••••••••" : "未配置"}
                      defaultValue=""
                      onChange={(e) => setEditValues((prev) => ({ ...prev, [keyInfo.id]: e.target.value }))}
                      className="flex-1 px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-blue-300 font-mono"
                    />
                    <div className="flex items-center">
                      <div className={`w-2 h-2 rounded-full ${keyInfo.configured ? "bg-green-400" : "bg-gray-300"}`} />
                    </div>
                  </div>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    {keyInfo.configured ? `已配置 · 当前值 ${keyInfo.masked_value}` : "未配置"}
                  </p>
                </div>
              ))}
              <div className="flex items-center gap-2 pt-2">
                <button
                  onClick={handleSaveKeys}
                  disabled={saving || Object.keys(editValues).length === 0}
                  className="px-4 py-2 text-xs font-medium bg-[#1a65e1] text-white rounded-lg hover:bg-blue-600 disabled:opacity-40 transition-colors"
                >
                  {saving ? "保存中..." : "保存密钥"}
                </button>
                {message && (
                  <span className={`text-xs ${message.includes("失败") ? "text-red-500" : "text-green-500"}`}>{message}</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   PipelineBar — 动态阶段进度卡
   ════════════════════════════════════════════════════════════ */

const stageColorMap: Record<string, string> = {
  qc:       "#4785f0",
  segment:  "#4f93ed",
  keyframe: "#5799e9",
  audio:    "#5ca8e8",
  align:    "#63b4e0",
  caption:  "#67c4c0",
  embed:    "#60c9a8",
  summary:  "#55c890",
};

