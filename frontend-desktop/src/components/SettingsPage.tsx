/* ════════════════════════════════════════════════════════════
   SettingsPage — 系统设置
   左导航四项（按「控制对象」划分）：
    1. 系统：存储路径 / NVDEC / chunk / 并发管道上限（管道级基础设施）
    2. 模型参数：编码（Embedder）卡 + 物体检测（YOLO）卡，同模型同卡
    3. 参数预设：多套命名参数快照，一键套用 / 重命名 / 删除
    4. API 密钥：DashScope / DeepSeek 端点 + 模型名 + 密钥
   保存即写入 data/settings.json 并运行时生效（无需重启；量化需重启）。
   布局：左导航固定 + 右内容独立滚动（与工作台面板一致）。
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { EncodeProfileSettingsUpdate, PipelineConfigInfo, PipelinePreset, PipelineSettingsUpdate, SettingsData, SettingsUpdate } from "../types";
import { fmtFullDate } from "../utils/helpers";

const PROVIDER_IDS = ["dashscope", "deepseek"] as const;
const PROVIDER_HINT: Record<string, string> = {
  dashscope: "画面描述（caption，vlm_llm 模式）",
  deepseek: "摘要生成（summary，vlm_llm 模式）",
};

/* ── 编码三档模板：显示名 + 推荐参数（placeholder 显示，按 embedding_profile 档位切换）── */
const ENCODE_PROFILE_IDS = ["fast", "balanced", "precise"] as const;
const ENCODE_PROFILE_LABEL: Record<string, string> = {
  fast: "快速 fast",
  balanced: "平衡 balanced",
  precise: "精准 precise",
};
const ENCODE_PROFILE_RECOMMEND: Record<string, { encode_width: number; encode_height: number; encode_batch_size: number }> = {
  fast: { encode_width: 336, encode_height: 224, encode_batch_size: 512 },
  balanced: { encode_width: 504, encode_height: 336, encode_batch_size: 512 },
  precise: { encode_width: 672, encode_height: 448, encode_batch_size: 256 },
};
/* 2b 低显存档推荐（与后端 config_loader._2B_ENCODE_DEFAULTS 对齐）*/
const ENCODE_PROFILE_RECOMMEND_2B: Record<string, { encode_width: number; encode_height: number; encode_batch_size: number }> = {
  fast: { encode_width: 336, encode_height: 224, encode_batch_size: 256 },
  balanced: { encode_width: 448, encode_height: 224, encode_batch_size: 256 },
  precise: { encode_width: 448, encode_height: 336, encode_batch_size: 128 },
};
const profileRecommendFor = (profile?: string) =>
  profile === "2b" ? ENCODE_PROFILE_RECOMMEND_2B : ENCODE_PROFILE_RECOMMEND;
const strOr = (v: number | undefined): string => (v != null ? String(v) : "");

/* ── 统一样式（模块级，供各子组件复用） ── */
const cardCls = "bg-white rounded-[var(--radius-lg)] border border-[var(--color-border-light)] shadow-[var(--shadow-card)] p-6";
const inputCls = "w-full px-3 py-2 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg text-sm text-[var(--color-text-primary)] placeholder:text-gray-400 outline-none focus:border-[var(--color-accent-blue)] focus:ring-2 focus:ring-teal-600/15 transition-colors";
const inputSmCls = "w-full px-2 py-1.5 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-md text-xs text-[var(--color-text-primary)] placeholder:text-gray-400 outline-none focus:border-[var(--color-accent-blue)] focus:ring-1 focus:ring-teal-600/15 transition-colors";
const labelCls = "text-xs text-[var(--color-text-muted)] mb-1.5 block";
const hintCls = "text-[10px] text-[var(--color-text-dim)] mt-1 leading-relaxed";
const cardTitleCls = "text-sm font-semibold text-[var(--color-text-primary)] mb-1";
const cardDescCls = "text-[11px] text-[var(--color-text-dim)] mb-4 leading-relaxed";

type SettingsSection = "system" | "model";
export type { SettingsSection };

/* ═══════════════════════ 系统设置：① 参数预设 ═══════════════════════ */
function PresetSection({
  presets, newPresetName, setNewPresetName,
  renamingId, setRenamingId, renameValue, setRenameValue,
  saving, onCreate, onApply, onRename, onDelete,
}: {
  presets: PipelinePreset[];
  newPresetName: string;
  setNewPresetName: (v: string) => void;
  renamingId: string | null;
  setRenamingId: (v: string | null) => void;
  renameValue: string;
  setRenameValue: (v: string) => void;
  saving: string | null;
  onCreate: () => void;
  onApply: (p: PipelinePreset) => void;
  onRename: (p: PipelinePreset) => void;
  onDelete: (p: PipelinePreset) => void;
}) {
  return (
    <>
      {/* ── 保存当前参数为新预设 ── */}
      <div className={cardCls}>
        <h3 className={cardTitleCls}>保存当前参数为新预设</h3>
        <p className={cardDescCls}>把当前生效的管道性能 / 模型参数存成一套命名快照（未保存的编辑请先点对应卡片「保存」）；预设不含存储路径与 API 密钥</p>
        <div className="flex gap-3">
          <input type="text" value={newPresetName} placeholder="如：开发机 GB10 / 24GB 推荐"
            onChange={(e) => setNewPresetName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onCreate(); }}
            className={inputCls} />
          <button onClick={onCreate} disabled={saving === "preset-create"} className="g-btn g-btn-primary shrink-0">
            {saving === "preset-create" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>

      {/* ── 已有预设 ── */}
      <div className={cardCls}>
        <h3 className={cardTitleCls}>已有预设</h3>
        <p className={cardDescCls}>一键套用任意一套参数（写入当前生效配置；量化需重启后端）</p>
        {presets.length === 0 ? (
          <p className="text-xs text-[var(--color-text-dim)] py-2">暂无预设，先在上方保存一套</p>
        ) : (
          <div className="space-y-2">
            {presets.map((p) => {
              const isRenaming = renamingId === p.id;
              return (
                <div key={p.id} className="border border-[var(--color-border-light)] rounded-lg p-3 flex items-center gap-3">
                  {isRenaming ? (
                    <input type="text" value={renameValue} autoFocus
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") onRename(p);
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className={`${inputCls} flex-1`} />
                  ) : (
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium text-[var(--color-text-primary)] truncate">{p.name}</div>
                      <div className="text-[10px] text-[var(--color-text-dim)]">
                        {p.created_at ? fmtFullDate(p.created_at) : ""}
                      </div>
                    </div>
                  )}
                  {!isRenaming && (
                    <button onClick={() => onApply(p)} disabled={saving === `apply-${p.id}`}
                      className="px-2.5 py-1 text-[11px] font-medium bg-[#4f7cff] text-white rounded-md hover:bg-[#4369f5] disabled:opacity-40 transition-colors cursor-pointer flex-shrink-0">
                      {saving === `apply-${p.id}` ? "套用中..." : "套用"}
                    </button>
                  )}
                  {isRenaming ? (
                    <button onClick={() => onRename(p)} disabled={saving === `rename-${p.id}`}
                      className="px-2.5 py-1 text-[11px] font-medium bg-[#4f7cff] text-white rounded-md hover:bg-[#4369f5] disabled:opacity-40 transition-colors cursor-pointer flex-shrink-0">
                      确定
                    </button>
                  ) : (
                    <button onClick={() => { setRenamingId(p.id); setRenameValue(p.name); }}
                      className="px-2.5 py-1 text-[11px] font-medium border border-[var(--color-border)] rounded-md text-[var(--color-text-muted)] hover:bg-[var(--color-surface)] transition-colors cursor-pointer flex-shrink-0">
                      重命名
                    </button>
                  )}
                  <button onClick={() => onDelete(p)} disabled={saving === `del-${p.id}`}
                    className="px-2.5 py-1 text-[11px] font-medium border border-red-200 rounded-md text-red-500 hover:bg-red-50 transition-colors cursor-pointer flex-shrink-0">
                    删除
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

/* ═══════════════════════ 系统设置：② 存储路径 ═══════════════════════ */
function StorageSection({
  storageEdit, setStorageEdit, saving, onSave,
}: {
  storageEdit: { video_dir: string; artifact_dir: string };
  setStorageEdit: (e: { video_dir: string; artifact_dir: string }) => void;
  saving: string | null;
  onSave: () => void;
}) {
  return (
    <div className={cardCls}>
      <h3 className={cardTitleCls}>存储路径</h3>
      <p className={cardDescCls}>新上传的视频与处理制品存放目录，保存后新上传 / 转码 / 导出立即生效</p>
      <div className="space-y-4">
        <div>
          <label className={labelCls}>视频目录</label>
          <input type="text" value={storageEdit.video_dir} placeholder="data/videos"
            onChange={(e) => setStorageEdit({ ...storageEdit, video_dir: e.target.value })}
            className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>制品目录</label>
          <input type="text" value={storageEdit.artifact_dir} placeholder="data/artifacts"
            onChange={(e) => setStorageEdit({ ...storageEdit, artifact_dir: e.target.value })}
            className={inputCls} />
        </div>
        <div className="flex justify-end">
          <button onClick={onSave} disabled={saving === "storage"} className="g-btn g-btn-primary">
            {saving === "storage" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ 系统设置：③ 管道设置 ═══════════════════════ */
function PipelineSection({
  pipelineEdit, setPipelineEdit, saving, onSave,
}: {
  pipelineEdit: PipelineSettingsUpdate;
  setPipelineEdit: (p: PipelineSettingsUpdate) => void;
  saving: string | null;
  onSave: () => void;
}) {
  return (
    <div className={cardCls}>
      <h3 className={cardTitleCls}>管道设置</h3>
      <p className={cardDescCls}>解码与编码路径开关、并发管道上限（低显存机器防批量并发 OOM；留空并保存恢复配置默认）</p>
      <div className="space-y-4">
        <div className="flex gap-6">
          <label className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)] cursor-pointer">
            <input type="checkbox" checked={!!pipelineEdit.use_nvdec}
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, use_nvdec: e.target.checked })}
              className="w-3.5 h-3.5 accent-teal-600" />
            NVDEC 硬解
          </label>
          <label className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)] cursor-pointer">
            <input type="checkbox" checked={!!pipelineEdit.chunk_encoding}
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, chunk_encoding: e.target.checked })}
              className="w-3.5 h-3.5 accent-teal-600" />
            chunk 编码
          </label>
        </div>
        <div>
          <label className={labelCls}>并发管道上限 (max_concurrent_videos)</label>
          <input type="number" min={0} max={16} step={1} value={pipelineEdit.max_concurrent_videos} placeholder="0"
            onChange={(e) => setPipelineEdit({ ...pipelineEdit, max_concurrent_videos: e.target.value })}
            className={inputCls} />
          <p className={hintCls}>推荐 0（不限）；0-16。24GB 建议 1（激活峰值按并发数叠加）</p>
        </div>
        {/* 场景分割（v0.33：从参数面板高级参数移入，全局生效） */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>采样帧率 (sample_fps)</label>
            <input type="number" min={0.5} max={3.0} step={0.1} value={pipelineEdit.sample_fps} placeholder="1.0"
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, sample_fps: e.target.value })}
              className={inputCls} />
            <p className={hintCls}>TransNetV2 镜头分割采样帧率；0.5-3.0（留空恢复默认）</p>
          </div>
          <div>
            <label className={labelCls}>场景切换敏感度 (segment_threshold)</label>
            <input type="number" min={0.2} max={0.8} step={0.1} value={pipelineEdit.segment_threshold} placeholder="0.5"
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, segment_threshold: e.target.value })}
              className={inputCls} />
            <p className={hintCls}>0.2 敏感 / 0.8 保守（留空恢复默认）</p>
          </div>
        </div>
        <div className="flex justify-end">
          <button onClick={onSave} disabled={saving === "system"} className="g-btn g-btn-primary">
            {saving === "system" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ 模型参数：① 编码 ═══════════════════════ */
function EncoderSection({
  pipelineEdit, setPipelineEdit, profileEdit, setProfileEdit, saving, onSave, profileInfo,
}: {
  pipelineEdit: PipelineSettingsUpdate;
  setPipelineEdit: (p: PipelineSettingsUpdate) => void;
  profileEdit: Record<string, EncodeProfileSettingsUpdate>;
  setProfileEdit: (updater: (prev: Record<string, EncodeProfileSettingsUpdate>) => Record<string, EncodeProfileSettingsUpdate>) => void;
  saving: string | null;
  onSave: () => void;
  profileInfo: PipelineConfigInfo | null;
}) {
  const profile = profileInfo?.embedding_profile || "8b";
  const dim = profileInfo?.embedding_profiles?.[profile]?.dimension;
  const recTable = profileRecommendFor(profile);
  return (
    <div className={cardCls + " xl:col-span-2"}>
      <div className="flex items-start justify-between gap-2 mb-1">
        <h3 className={cardTitleCls}>编码（Embedder）</h3>
        <span className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-[var(--color-accent-blue)]/10 text-[var(--color-accent-blue)]">
          {profile === "2b" ? `当前档位 2B${dim ? ` · ${dim} 维` : ""}` : `当前档位 8B${dim ? ` · ${dim} 维` : ""}`}
        </span>
      </div>
      <p className={cardDescCls}>三档编码模板可各调分辨率与批大小（placeholder 为{profile === "2b" ? "2B 档推荐值" : "推荐值"}）；参数面板选档 = 用该档值。分辨率 224-960，批大小 8-1024（8 倍数）</p>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>默认编码预设 (default_encode_profile)</label>
            <select value={pipelineEdit.default_encode_profile}
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, default_encode_profile: e.target.value })}
              className={inputCls}>
              <option value="">跟随 config.yaml</option>
              {ENCODE_PROFILE_IDS.map((pid) => (
                <option key={pid} value={pid}>{ENCODE_PROFILE_LABEL[pid]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>Embedder 量化 (quantization)</label>
            <select value={pipelineEdit.quantization}
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, quantization: e.target.value })}
              className={inputCls}>
              <option value="">跟随 {profile === "2b" ? "2B 档默认（none）" : "config.yaml"}</option>
              <option value="none">none（FP16，质量最好）</option>
              <option value="8bit">8bit（{profile === "2b" ? "~2GB，可选省显存" : "~8GB，24GB 卡推荐"}）</option>
              <option value="4bit">4bit（{profile === "2b" ? "~1GB，最省" : "~4GB，最省"}）</option>
            </select>
            {profile === "2b" ? (
              <p className={hintCls}>⚠️ 需重启后端；2B 模型约 4GB，本机 8GB 显存默认 none 即可，无需量化；8bit/4bit 需 pip install bitsandbytes</p>
            ) : (
              <p className={hintCls}>⚠️ 需重启后端；8bit/4bit 需 pip install bitsandbytes</p>
            )}
          </div>
        </div>

        {/* 三档模板表格 */}
        <div>
          <label className={labelCls}>三档编码模板（分辨率宽 × 高 / 批大小）</label>
          <div className="border border-[var(--color-border-light)] rounded-lg overflow-hidden">
            <div className="grid grid-cols-[96px_1fr_1fr_1fr] gap-2 px-3 py-2 bg-[var(--color-surface)] text-[10px] text-[var(--color-text-dim)] font-medium">
              <span>档位</span><span>分辨率宽</span><span>分辨率高</span><span>批大小</span>
            </div>
            {ENCODE_PROFILE_IDS.map((pid) => {
              const p = profileEdit[pid] ?? {};
              const rec = recTable[pid];
              return (
                <div key={pid} className="grid grid-cols-[96px_1fr_1fr_1fr] gap-2 px-3 py-2 border-t border-[var(--color-border-light)]">
                  <span className="text-xs font-medium text-[var(--color-text-secondary)] self-center">{ENCODE_PROFILE_LABEL[pid]}</span>
                  <input type="number" min={224} max={960} step={1} value={p.encode_width}
                    placeholder={String(rec.encode_width)}
                    onChange={(e) => setProfileEdit((prev) => ({ ...prev, [pid]: { ...prev[pid], encode_width: e.target.value } }))}
                    className={inputSmCls} />
                  <input type="number" min={224} max={960} step={1} value={p.encode_height}
                    placeholder={String(rec.encode_height)}
                    onChange={(e) => setProfileEdit((prev) => ({ ...prev, [pid]: { ...prev[pid], encode_height: e.target.value } }))}
                    className={inputSmCls} />
                  <input type="number" min={8} max={1024} step={8} value={p.encode_batch_size}
                    placeholder={String(rec.encode_batch_size)}
                    onChange={(e) => setProfileEdit((prev) => ({ ...prev, [pid]: { ...prev[pid], encode_batch_size: e.target.value } }))}
                    className={inputSmCls} />
                </div>
              );
            })}
          </div>
          <p className={hintCls}>留空 = 该档该字段保持 config 默认；保存后参数面板选档即生效该档模板</p>
        </div>

        <div className="flex justify-end">
          <button onClick={onSave} disabled={saving === "encode"} className="g-btn g-btn-primary">
            {saving === "encode" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ 模型参数：② 物体检测 ═══════════════════════ */
function DetectionSection({
  pipelineEdit, setPipelineEdit, saving, onSave,
}: {
  pipelineEdit: PipelineSettingsUpdate;
  setPipelineEdit: (p: PipelineSettingsUpdate) => void;
  saving: string | null;
  onSave: () => void;
}) {
  return (
    <div className={cardCls}>
      <h3 className={cardTitleCls}>物体检测（YOLO）</h3>
      <p className={cardDescCls}>检测帧率 / GPU 批大小 / 推理分辨率 / 置信度与 IoU 阈值（批大小与分辨率直接决定 YOLO 显存峰值）</p>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>检测帧率 (detection_fps)</label>
            <input type="number" min={1} max={30} step={1} value={pipelineEdit.detection_fps} placeholder="10"
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, detection_fps: e.target.value })}
              className={inputCls} />
            <p className={hintCls}>推荐 10；1-30</p>
          </div>
          <div>
            <label className={labelCls}>YOLO 批大小 (detector_batch_size)</label>
            <input type="number" min={1} max={512} step={1} value={pipelineEdit.detector_batch_size} placeholder="128"
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, detector_batch_size: e.target.value })}
              className={inputCls} />
            <p className={hintCls}>推荐 128；1-512</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>置信度阈值 (confidence_threshold)</label>
            <input type="number" min={0.05} max={0.95} step={0.05} value={pipelineEdit.confidence_threshold} placeholder="0.4"
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, confidence_threshold: e.target.value })}
              className={inputCls} />
            <p className={hintCls}>推荐 0.4；0.05-0.95</p>
          </div>
          <div>
            <label className={labelCls}>IoU 阈值 (iou_threshold)</label>
            <input type="number" min={0.05} max={0.9} step={0.05} value={pipelineEdit.iou_threshold} placeholder="0.5"
              onChange={(e) => setPipelineEdit({ ...pipelineEdit, iou_threshold: e.target.value })}
              className={inputCls} />
            <p className={hintCls}>推荐 0.5；0.05-0.9</p>
          </div>
        </div>
        <div>
          <label className={labelCls}>YOLO 推理分辨率 (yolo_imgsz)</label>
          <input type="number" min={320} max={640} step={32} value={pipelineEdit.yolo_imgsz} placeholder="640"
            onChange={(e) => setPipelineEdit({ ...pipelineEdit, yolo_imgsz: e.target.value })}
            className={inputCls} />
          <p className={hintCls}>推荐 640（32 倍数）；320-640。512 / 416 激活近似减半，检测精度略降</p>
        </div>
        <div className="flex justify-end">
          <button onClick={onSave} disabled={saving === "detect"} className="g-btn g-btn-primary">
            {saving === "detect" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════ 模型参数：③ API 密钥与服务 ═══════════════════════ */
function ApiKeysSection({
  settings, providerEdit, setProviderEdit, apiKeyEdit, setApiKeyEdit, saving, onSave,
}: {
  settings: SettingsData | null;
  providerEdit: Record<string, { base_url: string; model: string }>;
  setProviderEdit: (p: Record<string, { base_url: string; model: string }>) => void;
  apiKeyEdit: Record<string, string>;
  setApiKeyEdit: (p: Record<string, string>) => void;
  saving: string | null;
  onSave: () => void;
}) {
  return (
    <div className={cardCls}>
      <h3 className={cardTitleCls}>API 密钥与服务</h3>
      <p className={cardDescCls}>摘要 vlm_llm 模式使用；端点 + 模型名 + 密钥均可改（密钥留空则保持不变）</p>
      <div className="space-y-4">
        {PROVIDER_IDS.map((pid) => {
          const keyInfo = settings?.api_keys?.[pid];
          const edit = providerEdit[pid] ?? { base_url: "", model: "" };
          return (
            <div key={pid} className="border border-[var(--color-border-light)] rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--color-text-secondary)]">{keyInfo?.label ?? pid}</span>
                <span className="flex items-center gap-1.5 text-[10px] text-[var(--color-text-dim)]">
                  <span className={`inline-block w-2 h-2 rounded-full ${keyInfo?.configured ? "bg-[var(--color-accent-green)]" : "bg-gray-300"}`} />
                  {keyInfo?.configured ? `已配置 · ${keyInfo.masked_value}` : "密钥未配置"}
                </span>
              </div>
              <div>
                <label className={labelCls}>接口地址 (Base URL)</label>
                <input type="text" value={edit.base_url} placeholder="https://..."
                  onChange={(e) => setProviderEdit({ ...providerEdit, [pid]: { ...providerEdit[pid], base_url: e.target.value } })}
                  className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>模型名</label>
                <input type="text" value={edit.model} placeholder={pid === "dashscope" ? "qwen-vl-max" : "deepseek-chat"}
                  onChange={(e) => setProviderEdit({ ...providerEdit, [pid]: { ...providerEdit[pid], model: e.target.value } })}
                  className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>API 密钥（{PROVIDER_HINT[pid]}）</label>
                <input type="password" placeholder={keyInfo?.configured ? "••••••••（留空保持不变）" : "未配置"}
                  value={apiKeyEdit[pid] ?? ""}
                  onChange={(e) => setApiKeyEdit({ ...apiKeyEdit, [pid]: e.target.value })}
                  className={inputCls} />
              </div>
            </div>
          );
        })}
        <div className="flex justify-end">
          <button onClick={onSave} disabled={saving === "keys"} className="g-btn g-btn-primary">
            {saving === "keys" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SettingsPage({
  section,
  onSectionChange,
}: {
  section: SettingsSection;
  onSectionChange?: (s: SettingsSection) => void;
}) {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  // 当前 vector embedding 档位（GET /settings/pipeline）——设置页按 2b/8b 显示徽标与推荐
  const [profileInfo, setProfileInfo] = useState<PipelineConfigInfo | null>(null);

  // 编辑态
  const [apiKeyEdit, setApiKeyEdit] = useState<Record<string, string>>({});
  const [providerEdit, setProviderEdit] = useState<Record<string, { base_url: string; model: string }>>({});
  const [storageEdit, setStorageEdit] = useState<{ video_dir: string; artifact_dir: string }>({
    video_dir: "",
    artifact_dir: "",
  });
  // 空字符串 = 删除覆盖（回退 config.yaml 默认值）；布尔字段为显式开关
  const [pipelineEdit, setPipelineEdit] = useState<PipelineSettingsUpdate>({
    default_encode_profile: "",
    detection_fps: "",
    detector_batch_size: "",
    confidence_threshold: "",
    iou_threshold: "",
    use_nvdec: true,
    chunk_encoding: false,
    quantization: "",
    yolo_imgsz: "",
    max_concurrent_videos: "",
    sample_fps: "",
    segment_threshold: "",
  });
  // 编码三档模板编辑态（各档独立分辨率 + 批大小）
  const [profileEdit, setProfileEdit] = useState<Record<string, EncodeProfileSettingsUpdate>>({
    fast: { encode_width: "", encode_height: "", encode_batch_size: "" },
    balanced: { encode_width: "", encode_height: "", encode_batch_size: "" },
    precise: { encode_width: "", encode_height: "", encode_batch_size: "" },
  });

  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // 参数预设
  const [presets, setPresets] = useState<PipelinePreset[]>([]);
  const [newPresetName, setNewPresetName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const loadPresets = () => {
    api.getPresets().then((data) => setPresets(data ?? [])).catch(() => setPresets([]));
  };

  const handleCreatePreset = async () => {
    if (!newPresetName.trim()) { flash("err", "请先输入预设名称"); return; }
    setSaving("preset-create"); setMsg(null);
    try {
      await api.createPreset(newPresetName.trim());
      setNewPresetName("");
      loadPresets();
      flash("ok", `已保存当前参数为新预设「${newPresetName.trim()}」`);
    } catch (e) { flash("err", e instanceof Error ? e.message : "创建失败"); }
    finally { setSaving(null); }
  };

  const handleApplyPreset = async (p: PipelinePreset) => {
    setSaving(`apply-${p.id}`); setMsg(null);
    try {
      await api.applyPreset(p.id);
      load();            // 刷新设置表单，反映套用后的值
      flash("ok", `已套用预设「${p.name}」（量化需重启后端生效）`);
    } catch (e) { flash("err", e instanceof Error ? e.message : "套用失败"); }
    finally { setSaving(null); }
  };

  const handleRenamePreset = async (p: PipelinePreset) => {
    if (!renameValue.trim()) { setRenamingId(null); return; }
    setSaving(`rename-${p.id}`); setMsg(null);
    try {
      await api.renamePreset(p.id, renameValue.trim());
      setRenamingId(null);
      loadPresets();
      flash("ok", "预设已重命名");
    } catch (e) { flash("err", e instanceof Error ? e.message : "重命名失败"); }
    finally { setSaving(null); }
  };

  const handleDeletePreset = async (p: PipelinePreset) => {
    if (!window.confirm(`删除预设「${p.name}」？`)) return;
    setSaving(`del-${p.id}`); setMsg(null);
    try {
      await api.deletePreset(p.id);
      loadPresets();
      flash("ok", `已删除预设「${p.name}」`);
    } catch (e) { flash("err", e instanceof Error ? e.message : "删除失败"); }
    finally { setSaving(null); }
  };

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
      setPipelineEdit({
        default_encode_profile: data.pipeline?.default_encode_profile ?? "",
        detection_fps: data.pipeline?.detection_fps != null ? String(data.pipeline.detection_fps) : "",
        detector_batch_size: data.pipeline?.detector_batch_size != null ? String(data.pipeline.detector_batch_size) : "",
        confidence_threshold: data.pipeline?.confidence_threshold != null ? String(data.pipeline.confidence_threshold) : "",
        iou_threshold: data.pipeline?.iou_threshold != null ? String(data.pipeline.iou_threshold) : "",
        use_nvdec: data.pipeline?.use_nvdec ?? true,
        chunk_encoding: data.pipeline?.chunk_encoding ?? false,
        quantization: data.pipeline?.quantization ?? "",
        yolo_imgsz: data.pipeline?.yolo_imgsz != null ? String(data.pipeline.yolo_imgsz) : "",
        max_concurrent_videos: data.pipeline?.max_concurrent_videos != null ? String(data.pipeline.max_concurrent_videos) : "",
        sample_fps: data.pipeline?.sample_fps != null ? String(data.pipeline.sample_fps) : "",
        segment_threshold: data.pipeline?.segment_threshold != null ? String(data.pipeline.segment_threshold) : "",
      });
      const profiles = data.pipeline?.encode_profiles ?? {};
      setProfileEdit({
        fast: {
          encode_width: strOr(profiles.fast?.encode_width),
          encode_height: strOr(profiles.fast?.encode_height),
          encode_batch_size: strOr(profiles.fast?.encode_batch_size),
        },
        balanced: {
          encode_width: strOr(profiles.balanced?.encode_width),
          encode_height: strOr(profiles.balanced?.encode_height),
          encode_batch_size: strOr(profiles.balanced?.encode_batch_size),
        },
        precise: {
          encode_width: strOr(profiles.precise?.encode_width),
          encode_height: strOr(profiles.precise?.encode_height),
          encode_batch_size: strOr(profiles.precise?.encode_batch_size),
        },
      });
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { loadPresets(); }, []);
  // 档位信息（独立于 settings.json 的当前生效配置）：设置页据此显示档位徽标 + 按档推荐
  useEffect(() => {
    api.getPipelineConfig().then(setProfileInfo).catch(() => setProfileInfo(null));
  }, []);

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
      flash("ok", "API 密钥与服务已保存，运行时即时生效");
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

  const saveSystem = async () => {
    setSaving("system"); setMsg(null);
    try {
      await api.updateSettings({
        pipeline: {
          use_nvdec: pipelineEdit.use_nvdec,
          chunk_encoding: pipelineEdit.chunk_encoding,
          max_concurrent_videos: pipelineEdit.max_concurrent_videos,
          sample_fps: pipelineEdit.sample_fps,
          segment_threshold: pipelineEdit.segment_threshold,
        },
      });
      load();
      flash("ok", "管道设置已保存：NVDEC / chunk / 并发上限 / 场景分割对新视频运行时生效");
    } catch (e) { flash("err", e instanceof Error ? e.message : "保存失败"); }
    finally { setSaving(null); }
  };

  const saveEncode = async () => {
    setSaving("encode"); setMsg(null);
    try {
      await api.updateSettings({
        pipeline: {
          encode_profiles: profileEdit,
          default_encode_profile: pipelineEdit.default_encode_profile,
          quantization: pipelineEdit.quantization,
        },
      });
      load();
      flash("ok", "编码参数已保存：三档模板/默认预设/量化对新视频运行时生效（量化需重启）");
    } catch (e) { flash("err", e instanceof Error ? e.message : "保存失败"); }
    finally { setSaving(null); }
  };

  const saveDetect = async () => {
    setSaving("detect"); setMsg(null);
    try {
      await api.updateSettings({
        pipeline: {
          detection_fps: pipelineEdit.detection_fps,
          detector_batch_size: pipelineEdit.detector_batch_size,
          yolo_imgsz: pipelineEdit.yolo_imgsz,
          confidence_threshold: pipelineEdit.confidence_threshold,
          iou_threshold: pipelineEdit.iou_threshold,
        },
      });
      load();
      flash("ok", "检测参数已保存：帧率/批大小/分辨率/阈值对新视频运行时生效");
    } catch (e) { flash("err", e instanceof Error ? e.message : "保存失败"); }
    finally { setSaving(null); }
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* 内容（子页切换由左侧导航控制，见 AppContext settingsTab） */}
      <div className="p-2">
        <div className="w-full">
          {loading ? (
            <div className="space-y-4">
              <div className={`${cardCls} h-44 animate-pulse`} />
              <div className={`${cardCls} h-72 animate-pulse`} />
            </div>
          ) : section === "model" ? (
            /* ════════ 模型参数：编码 + 物体检测 + API 密钥与服务 ════════ */
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
              <EncoderSection
                pipelineEdit={pipelineEdit}
                setPipelineEdit={setPipelineEdit}
                profileEdit={profileEdit}
                setProfileEdit={setProfileEdit}
                saving={saving}
                onSave={saveEncode}
                profileInfo={profileInfo}
              />
              <DetectionSection
                pipelineEdit={pipelineEdit}
                setPipelineEdit={setPipelineEdit}
                saving={saving}
                onSave={saveDetect}
              />
              <ApiKeysSection
                settings={settings}
                providerEdit={providerEdit}
                setProviderEdit={setProviderEdit}
                apiKeyEdit={apiKeyEdit}
                setApiKeyEdit={setApiKeyEdit}
                saving={saving}
                onSave={saveKeys}
              />
            </div>
          ) : (
            /* ════════ 系统设置：参数预设 + 存储路径 + 管道设置 ════════ */
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
              <PresetSection
                presets={presets}
                newPresetName={newPresetName}
                setNewPresetName={setNewPresetName}
                renamingId={renamingId}
                setRenamingId={setRenamingId}
                renameValue={renameValue}
                setRenameValue={setRenameValue}
                saving={saving}
                onCreate={handleCreatePreset}
                onApply={handleApplyPreset}
                onRename={handleRenamePreset}
                onDelete={handleDeletePreset}
              />
              <StorageSection
                storageEdit={storageEdit}
                setStorageEdit={setStorageEdit}
                saving={saving}
                onSave={saveStorage}
              />
              <PipelineSection
                pipelineEdit={pipelineEdit}
                setPipelineEdit={setPipelineEdit}
                saving={saving}
                onSave={saveSystem}
              />
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
