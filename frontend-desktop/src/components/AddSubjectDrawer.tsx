/* ════════════════════════════════════════════════════════════
   AddSubjectDrawer — 轻量级沉淀 Drawer（v0.6 图片素材库）
   业务流（检测 track / 图搜结果）→「加入图片素材库」统一入口：
   自动携带首张底图（截帧 / track 缩略图 / 图搜缩略图），用户仅需
   补充名称与标签即可保存。保存后跳转素材库定位到新目标。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../AppContext";
import type { ImageSubject, ImageSubjectKind, SubjectPhoto } from "../types";
import { IconClose, IconBolt, IconPerson, IconSearch } from "./icons";
import { subjectsApi } from "../mocks/subjectsMock";

export interface AddSubjectDrawerData {
  kind: ImageSubjectKind;
  presetName?: string;
  /** 首张底图数据：blob（截帧）或 url（track/图搜缩略图，同源 fetch 转 blob） */
  image: { url?: string; blob?: Blob } | null;
  source?: SubjectPhoto["source"];
  sourceVideoId?: string | null;
  videoName?: string | null;
}

interface Props {
  data: AddSubjectDrawerData | null;
  onClose: () => void;
  /* 保存成功回调（默认行为：openImageLibrary 定位新目标） */
  onSaved?: (subjectId: string) => void;
}

/* 把 image 数据统一转成 File（url 同源 fetch → blob） */
async function imageToFile(image: { url?: string; blob?: Blob }, name: string): Promise<File> {
  if (image.blob) return new File([image.blob], name, { type: image.blob.type || "image/jpeg" });
  if (image.url) {
    const res = await fetch(image.url);
    if (!res.ok) throw new Error("底图加载失败");
    const blob = await res.blob();
    return new File([blob], name, { type: blob.type || "image/jpeg" });
  }
  throw new Error("无图片数据");
}

const TAG_PRESETS = ["在逃", "重点", "套牌车", "失窃车辆", "嫌疑人", "受害人"];

export function AddSubjectDrawer({ data, onClose, onSaved }: Props) {
  const { openImageLibrary } = useApp();
  const [kind, setKind] = useState<ImageSubjectKind>("person");
  const [name, setName] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const busyRef = useRef(false);

  /* 新建 / 已有目标 模式 */
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [existingSubjects, setExistingSubjects] = useState<ImageSubject[]>([]);
  const [selectedSubjectId, setSelectedSubjectId] = useState<string>("");
  const [subjectSearch, setSubjectSearch] = useState("");
  const [loadingSubjects, setLoadingSubjects] = useState(false);

  /* 打开时用 intent 初始化（数据变化即重置本地态）+ 加载已有目标 */
  useEffect(() => {
    if (!data) return;
    setKind(data.kind);
    setName(data.presetName ?? "");
    setTags([]);
    setTagDraft("");
    setError(null);
    setSaving(false);
    busyRef.current = false;
    setMode("new");
    setSelectedSubjectId("");
    setSubjectSearch("");
    /* 预览：blob → objectURL；url → 直接用 */
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return data.image?.blob ? URL.createObjectURL(data.image.blob) : (data.image?.url ?? null);
    });
    /* 加载同类型已有目标 */
    setLoadingSubjects(true);
    subjectsApi.listImageSubjects({ kind: data.kind })
      .then((list) => {
        setExistingSubjects(list);
        if (list.length > 0) setSelectedSubjectId(list[0].id);
      })
      .catch(() => setExistingSubjects([]))
      .finally(() => setLoadingSubjects(false));
  }, [data]);

  useEffect(() => {
    return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); };
  }, [previewUrl]);

  const addTag = (t: string) => {
    const v = t.trim();
    if (!v || tags.includes(v)) return;
    setTags((prev) => [...prev, v]);
  };
  const removeTag = (t: string) => setTags((prev) => prev.filter((x) => x !== t));

  /* 已有目标搜索过滤 */
  const filteredSubjects = useMemo(() => {
    if (!subjectSearch.trim()) return existingSubjects;
    const q = subjectSearch.trim().toLowerCase();
    return existingSubjects.filter((s) => s.name.toLowerCase().includes(q));
  }, [existingSubjects, subjectSearch]);

  async function handleSave() {
    if (!data || saving || busyRef.current) return;
    if (mode === "new" && !name.trim()) { setError("请填写目标名称"); return; }
    if (mode === "existing" && !selectedSubjectId) { setError("请选择一个已有目标"); return; }
    busyRef.current = true;
    setSaving(true);
    setError(null);
    try {
      let subjectId: string;
      if (mode === "new") {
        const subject = await subjectsApi.createImageSubject({ kind, name: name.trim(), tags });
        subjectId = subject.id;
      } else {
        subjectId = selectedSubjectId;
      }
      /* 首张底图：image 数据存在则上传（source 标记来源，溯源用） */
      if (data.image) {
        try {
          const fileName = mode === "new" ? name.trim() : (existingSubjects.find((s) => s.id === subjectId)?.name ?? "photo");
          const file = await imageToFile(data.image, `${fileName}_${Date.now()}.jpg`);
          await subjectsApi.uploadSubjectPhoto(subjectId, [file], data.source);
        } catch (e) {
          /* 底图上传失败不阻断目标创建，仅提示 */
          setError(e instanceof Error ? `底图上传失败：${e.message}` : "底图上传失败");
        }
      }
      onClose();
      if (onSaved) onSaved(subjectId);
      else openImageLibrary({ subjectId });
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      busyRef.current = false;
      setSaving(false);
    }
  }

  if (!data) return null;

  return (
    <div className="fl-drawer-overlay" onClick={onClose}>
      <div className="fl-drawer" onClick={(e) => e.stopPropagation()} style={{ width: 400 }}>
        <div className="fl-drawer-hd">
          <span className="flex items-center gap-1.5 text-[14px] font-semibold text-gray-900">
            <span className="text-[#4f7cff]"><IconBolt /></span>
            加入图片素材库
          </span>
          <button className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors shrink-0" title="关闭" onClick={onClose}>
            <IconClose />
          </button>
        </div>

        <div className="fl-drawer-body">
          {/* 底图预览：自动截取/缩略图 */}
          <div className="relative w-full h-[200px] bg-[#0b0f16] rounded-lg overflow-hidden flex items-center justify-center">
            {previewUrl ? (
              <img src={previewUrl} alt="底图" className="max-w-full max-h-full object-contain" />
            ) : (
              <span className="text-[12px] text-white/40">未携带底图，保存后可到素材库补充</span>
            )}
            {data.source === "track" && (
              <span className="absolute left-2 top-2 text-[10px] px-1.5 py-0.5 rounded bg-black/60 text-white/80">来自检测沉淀</span>
            )}
            {data.source === "search" && (
              <span className="absolute left-2 top-2 text-[10px] px-1.5 py-0.5 rounded bg-black/60 text-white/80">来自图搜沉淀</span>
            )}
          </div>

          {/* 模式选择：新建 / 已有目标 */}
          <div className="mt-3">
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              <button
                type="button"
                className={"flex-1 h-[30px] text-[12px] font-medium transition-colors " +
                  (mode === "new" ? "bg-[#4f7cff] text-white" : "text-gray-500 hover:bg-gray-50")}
                onClick={() => setMode("new")}
              >
                新建目标
              </button>
              <button
                type="button"
                className={"flex-1 h-[30px] text-[12px] font-medium transition-colors " +
                  (mode === "existing" ? "bg-[#4f7cff] text-white" : "text-gray-500 hover:bg-gray-50")}
                onClick={() => setMode("existing")}
                disabled={existingSubjects.length === 0}
              >
                添加到已有目标{existingSubjects.length > 0 ? `（${existingSubjects.length}）` : ""}
              </button>
            </div>
          </div>

          {/* 已有目标下拉选择 */}
          {mode === "existing" && (
            <div className="mt-3">
              <label className="g-label !mb-1">选择目标</label>
              {loadingSubjects ? (
                <div className="text-[12px] text-gray-400 py-2">加载中…</div>
              ) : existingSubjects.length === 0 ? (
                <div className="text-[12px] text-gray-400 py-2">暂无同类型目标，请先新建</div>
              ) : (
                <>
                  <div className="relative mb-1.5">
                    <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400"><IconSearch /></span>
                    <input
                      className="g-input w-full !h-[30px] !text-[12px] !pl-7"
                      placeholder="搜索目标名称…"
                      value={subjectSearch}
                      onChange={(e) => setSubjectSearch(e.target.value)}
                    />
                  </div>
                  <div className="max-h-[160px] overflow-y-auto rounded-lg border border-gray-200 divide-y divide-gray-100">
                    {filteredSubjects.length === 0 ? (
                      <div className="text-[12px] text-gray-400 py-3 text-center">未找到匹配目标</div>
                    ) : (
                      filteredSubjects.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          className={"w-full flex items-center gap-2 px-2.5 py-2 text-left transition-colors " +
                            (selectedSubjectId === s.id ? "bg-[#4f7cff]/5 border-l-2 border-l-[#4f7cff]" : "hover:bg-gray-50 border-l-2 border-l-transparent")}
                          onClick={() => setSelectedSubjectId(s.id)}
                        >
                          <span className="w-6 h-6 rounded-full bg-gray-100 flex items-center justify-center shrink-0">
                            {s.kind === "person" ? <IconPerson /> : <span className="text-[10px] text-gray-400">物</span>}
                          </span>
                          <span className="flex-1 min-w-0">
                            <span className="block text-[12px] text-gray-800 truncate">{s.name}</span>
                            <span className="text-[10.5px] text-gray-400">{s.photo_count} 张</span>
                          </span>
                          {selectedSubjectId === s.id && (
                            <span className="text-[10px] text-[#4f7cff] font-medium">已选</span>
                          )}
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {/* 目标类型（仅新建模式） */}
          {mode === "new" && (
          <div className="mt-3">
            <label className="g-label !mb-1">目标类型</label>
            <div className="flex gap-1.5">
              {([["person", "人"], ["other", "其他"]] as [ImageSubjectKind, string][]).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  className={"flex-1 h-[32px] rounded-lg border text-[12.5px] font-medium transition-colors " +
                    (kind === k ? "border-[#4f7cff] bg-[#4f7cff]/5 text-[#4f7cff]" : "border-gray-200 text-gray-500 hover:border-gray-300")}
                  onClick={() => setKind(k)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          )}

          {/* 名称（仅新建模式） */}
          {mode === "new" && (
          <div className="mt-3">
            <label className="g-label !mb-1">名称 <span style={{ color: "#ef4444" }}>*</span></label>
            <input
              className="g-input w-full !h-[32px] !text-[12.5px]"
              placeholder={kind === "person" ? "如：嫌疑人张三" : "如：套牌车·京A12345"}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); }}
              autoFocus
            />
          </div>
          )}

          {/* 标签（仅新建模式） */}
          {mode === "new" && (
          <div className="mt-3">
            <label className="g-label !mb-1">标签</label>
            <div className="flex flex-wrap gap-1.5 mb-1.5">
              {TAG_PRESETS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={"px-2 py-0.5 rounded-full text-[11px] transition-colors " +
                    (tags.includes(t) ? "bg-[#4f7cff] text-white" : "bg-gray-100 text-gray-500 hover:bg-gray-200")}
                  onClick={() => (tags.includes(t) ? removeTag(t) : addTag(t))}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="flex gap-1.5">
              <input
                className="g-input flex-1 !h-[30px] !text-[12px]"
                placeholder="自定义标签，回车添加"
                value={tagDraft}
                onChange={(e) => setTagDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { addTag(tagDraft); setTagDraft(""); } }}
              />
              <button className="g-btn !h-[30px]" onClick={() => { addTag(tagDraft); setTagDraft(""); }}>添加</button>
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {tags.map((t) => (
                  <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#eaf1ff] text-[#4f7cff] text-[11px]">
                    {t}
                    <button type="button" className="hover:text-red-500" onClick={() => removeTag(t)}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
          )}

          {error && <div className="mt-2 text-[11.5px] text-red-500 bg-red-50 border border-red-100 rounded px-2 py-1.5">{error}</div>}
        </div>

        <div className="fl-drawer-ft">
          <button className="g-btn" onClick={onClose} disabled={saving}>取消</button>
          <button className="g-btn g-btn-primary" onClick={() => void handleSave()} disabled={saving}>
            {saving ? "保存中…" : mode === "new" ? "保存并加入素材库" : "添加到素材库"}
          </button>
        </div>
      </div>
    </div>
  );
}
