/* ════════════════════════════════════════════════════════════
   SmartSuggestDialog — 智能参数推荐弹窗（v0.36+）
   上传后弹出：左列每个视频展示 embedder zero-shot 推荐的场景 + 参数；
   右列可逐个编辑开关；底部「应用推荐并启动」「手动设置」「仅关闭」。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import type { SmartSuggestion, PipelineParams, VideoListItem } from "../types";
import { IconBolt, IconClose, IconRetry, IconInfo } from "./icons";

interface VideoInput {
  video_id: string;
  file_name: string;
}

interface SmartSuggestDialogProps {
  videos: VideoInput[];
  onClose: () => void;
  /* 应用并启动（批量解析） */
  onApply: (params: PipelineParams, videoIds: string[]) => Promise<void>;
}

export function SmartSuggestDialog({ videos, onClose, onApply }: SmartSuggestDialogProps) {
  const [suggestions, setSuggestions] = useState<SmartSuggestion[]>([]);
  const [overrides, setOverrides] = useState<Record<string, Partial<PipelineParams>>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  /* 加载推荐 */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.suggestParams(videos.map((v) => v.video_id))
      .then((data) => {
        if (cancelled) return;
        setSuggestions(data.suggestions ?? []);
      })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "智能推荐失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [videos]);

  /* 视频 id → 推荐参数映射 */
  const suggMap = useMemo(() => {
    const m: Record<string, SmartSuggestion> = {};
    for (const s of suggestions) m[s.video_id] = s;
    return m;
  }, [suggestions]);

  /* 最终生效参数（用户编辑 > 推荐 > 默认） */
  function effective(videoId: string, key: keyof PipelineParams): boolean | string | number | string[] | null {
    const o = overrides[videoId];
    if (o && key in o) return (o as any)[key];
    const s = suggMap[videoId];
    if (s?.params && key in s.params) return (s.params as any)[key];
    /* 默认：全开 summary=off 之外全关时太严格，给个保守默认 */
    if (key === "summary_enabled") return false;
    if (key === "summary_mode") return "vlm_llm";
    if (key === "content_type") return "general";
    return false;
  }

  function toggleOverride(videoId: string, key: keyof PipelineParams, value: any) {
    setOverrides((prev) => {
      const next = { ...prev };
      const cur = next[videoId] ?? {};
      next[videoId] = { ...cur, [key]: value };
      return next;
    });
  }

  /* 应用推荐：每个视频独立参数，analyzeBatch 单次调用（参数共享时） */
  /* 有明确场景 = 高置信推荐；无场景但有 params = 低置信兜底（默认参数） */
  const recommendedCount = suggestions.filter((s) => s.scene_key).length;
  const uncertainCount = suggestions.filter((s) => !s.scene_key).length;

  async function applyRecommended() {
    if (applying) return;
    setApplying(true);
    try {
      /* 智能推荐按场景类型分组，相同场景的视频共享一次 analyzeBatch 调用 */
      const byKey: Record<string, { ids: string[]; params: Partial<PipelineParams> }> = {};
      const manualIds: string[] = [];
      for (const v of videos) {
        const eff = buildEffectiveParams(v.video_id);
        const s = suggMap[v.video_id];
        if (s?.scene_key) {
          const k = s.scene_key;
          if (!byKey[k]) byKey[k] = { ids: [], params: eff };
          byKey[k].ids.push(v.video_id);
        } else {
          manualIds.push(v.video_id);
        }
      }
      for (const k of Object.keys(byKey)) {
        await onApply(byKey[k].params as PipelineParams, byKey[k].ids);
      }
      /* 不确定的视频：使用 effective 参数单视频启动（PUT /params） */
      for (const id of manualIds) {
        await onApply(buildEffectiveParams(id) as PipelineParams, [id]);
      }
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "应用推荐失败");
    } finally {
      setApplying(false);
    }
  }

  function buildEffectiveParams(videoId: string): PipelineParams {
    const s = suggMap[videoId];
    const fallback: PipelineParams = {
      content_type: "general",
      vision_enabled: true,
      audio_enabled: false,
      ocr_enabled: false,
      caption_enabled: false,
      detection_enabled: false,
      detection_classes: null,
      face_enabled: false,
      plate_enabled: false,
      search_index_enabled: true,
      summary_enabled: false,
      summary_mode: "vlm_llm",
      language: "auto",
      sample_fps: 1.0,
      segment_threshold: 0.5,
      caption_with_context: true,
      summary_detail: "standard",
      encode_profile: null,
      apply_to_group: false,
    };
    const params: any = { ...fallback, ...(s?.params ?? {}), ...(overrides[videoId] ?? {}) };
    /* search_index_enabled 默认开 */
    params.search_index_enabled = effective(videoId, "search_index_enabled") as boolean;
    return params as PipelineParams;
  }

  return (
    <div className="g-modal-overlay">
      <div className="g-modal" style={{ width: 720, height: "min(620px, 84vh)" }}>
        <div className="g-card-hd">
          <span className="g-card-tt">
            <IconBolt />
            智能参数推荐
          </span>
          <button className="modal-x" onClick={onClose} title="关闭" aria-label="关闭">×</button>
        </div>

        <div className="ss-body">
          <div className="ss-summary">
            {loading ? (
              <span className="ss-tip"><i className="gs-spin" />正在通过本地嵌入模型分析视频场景…</span>
            ) : error ? (
              <span className="ss-err"><IconInfo />{error} <button className="ss-retry" onClick={() => location.reload()}><IconRetry />重试</button></span>
            ) : (
              <span className="ss-tip">
                已分析 <b>{videos.length}</b> 个视频；<b>{recommendedCount}</b> 个匹配推荐场景，<b>{uncertainCount}</b> 个不确定
                <span className="ss-hint">· 推荐仅供参考，可逐项调整</span>
              </span>
            )}
          </div>

          {!loading && !error && (
            <div className="ss-list">
              {videos.map((v) => {
                const s = suggMap[v.video_id];
                const reason = !s ? "无推荐" : !s.scene_key ? (s.reason === "low confidence" ? "低置信·默认参数" : (s.reason || "默认参数")) : null;
                const conf = s?.confidence ?? 0;
                return (
                  <div key={v.video_id} className={"ss-item" + (reason ? " uncertain" : "")}>
                    <div className="ss-item-head">
                      <span className="ss-name" title={v.file_name}>{v.file_name || v.video_id.slice(0, 8)}</span>
                      {s?.scene_label ? (
                        <span className="ss-scene" title={`匹配度 ${(conf * 100).toFixed(1)}%`}>
                          {s.scene_label}
                          <em>{(conf * 100).toFixed(0)}%</em>
                        </span>
                      ) : (
                        <span className="ss-scene ss-scene-none">{reason}</span>
                      )}
                    </div>
                    <div className="ss-toggles">
                      {([
                        ["detection_enabled", "物体检测"],
                        ["face_enabled", "人脸"],
                        ["plate_enabled", "车牌"],
                        ["ocr_enabled", "OCR 文字"],
                        ["search_index_enabled", "搜索索引"],
                      ] as [keyof PipelineParams, string][]).map(([k, label]) => (
                        <label key={k} className={"ss-toggle" + (effective(v.video_id, k) ? " on" : "")}>
                          <input
                            type="checkbox"
                            checked={Boolean(effective(v.video_id, k))}
                            onChange={(e) => toggleOverride(v.video_id, k, e.target.checked)}
                          />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="ss-ft">
          <button className="g-btn" onClick={onClose} disabled={applying}>关闭</button>
          <button className="g-btn g-btn-primary" onClick={applyRecommended} disabled={loading || applying || videos.length === 0}>
            {applying ? "启动中…" : `快速解析 (${videos.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}
