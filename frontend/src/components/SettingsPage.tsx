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

            <PipelineDefaultsSection />
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


/* ── Pipeline 默认值卡片 ── */

function PipelineDefaultsSection() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    fetch("/api/v1/settings/pipeline")
      .then((r) => r.json())
      .then((d) => setData(d.data))
      .catch(() => {});
  }, []);

  if (!data) return null;

  const profiles: Record<string, any> = data.encode_profiles ?? {};
  const defaultProfile = data.default_encode_profile ?? "balanced";

  return (
    <section>
      <h3 className="font-semibold text-gray-900 text-sm mb-3">
        Pipeline 调优
        <span className="text-[11px] font-normal text-gray-400 ml-2">编辑 config.yaml 后重启生效</span>
      </h3>
      <div className="space-y-2">
        {Object.entries(profiles).map(([key, p]: [string, any]) => {
          const isDefault = key === defaultProfile;
          return (
            <div
              key={key}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg border text-sm ${
                isDefault ? "bg-blue-50 border-blue-200" : "bg-gray-50 border-gray-150"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-medium ${isDefault ? "text-gray-900" : "text-gray-600"}`}>
                    {p.label ?? key}
                  </span>
                  {isDefault && (
                    <span className="text-[9px] px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded font-medium">默认</span>
                  )}
                </div>
                <span className="text-[10px] text-gray-400 block truncate">
                  {p.encode_width}×{p.encode_height} · batch={p.encode_batch_size} · {p.desc ?? ""}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex gap-2 text-[10px] text-gray-400">
        <span>NVDEC: {data.use_nvdec ? "ON" : "OFF"}</span>
        <span>·</span>
        <span>Chunk: {data.chunk_encoding ? "ON" : "OFF"}</span>
      </div>
    </section>
  );
}


