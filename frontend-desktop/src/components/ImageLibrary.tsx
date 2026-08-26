/* ════════════════════════════════════════════════════════════
   ImageLibrary — 素材库（v0.6）
   归档与管理「人脸 / 车辆 / 其他」等关注目标的底库照片。
   经典「左列表 + 右详情」分栏：
     ① IlHeader  顶部卡：标题 + 新建目标
     ② IlSide    左卡：名称搜索 + 目标卡片列表
     ③ IlDetail  右卡：主图 + 底库照片网格（拖拽扩充/裁剪/删除）
   核心原则：底库维护完全人工，无任何自动去重。
   ════════════════════════════════════════════════════════════ */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useApp } from "../AppContext";
import { subjectsApi, subjectPhotoUrl, subjectPrimaryUrl } from "../mocks/subjectsMock";
import type { ImageSubject, ImageSubjectKind, SubjectPhoto } from "../types";
import { IconPerson, IconCar, IconPlus, IconTrash, IconPencil, IconClose, IconSearch } from "./icons";

const KIND_LABEL: Record<ImageSubjectKind, string> = { person: "人", other: "其他" };
type Crop = { x1: number; y1: number; x2: number; y2: number };

/* ── 裁剪区域图片展示：按归一化 crop 精确对齐显示 ── */
function CroppedPhoto({ url, crop, className = "" }: { url: string; crop?: Crop | null; className?: string }) {
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  if (!crop) {
    return (
      <img
        src={url}
        alt=""
        loading="lazy"
        className={"w-full h-full object-cover " + className}
        onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.15"; }}
      />
    );
  }
  const cw = Math.max(0.02, crop.x2 - crop.x1);
  const ch = Math.max(0.02, crop.y2 - crop.y1);
  return (
    <div className={"relative overflow-hidden w-full h-full " + className}>
      <img
        src={url}
        alt=""
        loading="lazy"
        draggable={false}
        onLoad={(e) => {
          const el = e.target as HTMLImageElement;
          if (el.naturalWidth) setNat({ w: el.naturalWidth, h: el.naturalHeight });
        }}
        onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.15"; }}
        style={{
          position: "absolute", top: 0, left: 0, maxWidth: "none",
          width: nat ? `calc(100% / ${cw})` : "100%",
          height: nat ? `calc(100% / ${ch})` : "100%",
          transform: nat ? `translate(${-crop.x1 / cw * 100}%, ${-crop.y1 / ch * 100}%)` : undefined,
          objectFit: nat ? undefined : "cover",
        }}
      />
    </div>
  );
}

/* ═══════════════════ ① 顶部卡 ═══════════════════ */
function IlHeader({ onNew }: { onNew: () => void }) {
  return (
    <div className="case-card flex items-center justify-between flex-wrap gap-y-1.5 px-5 py-2 min-h-[56px] shrink-0">
      <div>
        <h1 className="text-[16px] font-semibold text-gray-900 leading-tight">素材库</h1>
        <p className="text-[12px] text-gray-500 leading-tight">人脸 / 车辆底库归档 · 人工维护 · 支持溯源</p>
      </div>
      <button className="g-btn g-btn-primary" onClick={onNew}>
        <IconPlus />
        新建目标
      </button>
    </div>
  );
}

/* ═══════════════════ ② 左卡：目标列表 ═══════════════════ */
function IlSide({
  subjects, search, setSearch, selectedId, onSelect, onDelete,
}: {
  subjects: ImageSubject[];
  search: string;
  setSearch: (s: string) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (s: ImageSubject) => void;
}) {
  return (
    <div className="w-[300px] shrink-0 case-card flex flex-col min-h-0">
      {/* 搜索工具条 */}
      <div className="px-3 pt-3 pb-2 border-b border-gray-100 shrink-0">
        <div className="relative">
          <input
            className="g-input w-full !h-[30px] !text-[12px] !pl-7" placeholder="搜索名称 / 标签"
            value={search} onChange={(e) => setSearch(e.target.value)}
          />
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400"><IconSearch /></span>
        </div>
      </div>

      {/* 目标卡片列表 */}
      <div className="flex-1 overflow-auto py-1.5">
        {subjects.length === 0 && (
          <div className="g-empty !py-14"><IconPerson /><span>暂无目标，点击「新建目标」</span></div>
        )}
        {subjects.map((s) => {
          const active = s.id === selectedId;
          const cnt = s.photo_count ?? 0;
          return (
            <div key={s.id}
              className={"group relative mx-1.5 px-3 py-2.5 rounded-md cursor-pointer border-l-[3px] transition-all duration-150 " +
                (active ? "bg-brand/5 border-[#4f7cff] shadow-sm" : "border-transparent hover:bg-white hover:shadow-sm")}
              onClick={() => onSelect(s.id)}
            >
              <div className="flex items-center gap-2.5">
                {/* 头像：主图（失败降级为类型图标） */}
                <div className="w-10 h-10 rounded-lg overflow-hidden shrink-0 bg-gray-50 flex items-center justify-center">
                  {cnt > 0 ? (
                    <img src={subjectPrimaryUrl(s.id)} alt="" className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                  ) : null}
                  <span className={"text-gray-300 " + (cnt > 0 ? "hidden" : "")}>
                    {s.kind === "person" ? <IconPerson /> : <IconCar />}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={"text-[13px] truncate " + (active ? "text-[#4f7cff] font-semibold" : "text-gray-800")}>{s.name}</span>
                    <span className={"shrink-0 text-[10px] px-1.5 rounded-full " + (s.kind === "person" ? "bg-blue-50 text-blue-600" : "bg-amber-50 text-amber-600")}>
                      {KIND_LABEL[s.kind]}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 mt-1 min-w-0">
                    {s.tags.slice(0, 2).map((t) => (
                      <span key={t} className="text-[10px] px-1.5 py-px rounded-full bg-red-50 text-red-500 shrink-0">{t}</span>
                    ))}
                    {s.tags.length === 0 && <span className="text-[10px] text-gray-300">无标签</span>}
                    <span className="ml-auto text-[10.5px] text-gray-500 shrink-0 font-mono">{cnt} 张</span>
                  </div>
                </div>
                <button className="p-1 rounded-md text-red-400 hover:text-red-600 hover:bg-red-50 transition-all flex-shrink-0" title="删除目标"
                  onClick={(e) => { e.stopPropagation(); onDelete(s); }}>
                  <IconTrash />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══════════════════ ③ 右卡：详情 ═══════════════════ */
function IlDetail({
  subject, photos,
  onRename, onTagsChange, onDeletePhoto, onSetPrimary, onCropPhoto, onTracePhoto,
  onDeleteSubject,
  onDropFiles,
  onUploadFiles,
}: {
  subject: ImageSubject;
  photos: SubjectPhoto[];
  onRename: (name: string) => void;
  onTagsChange: (tags: string[]) => void;
  onDeletePhoto: (p: SubjectPhoto) => void;
  onSetPrimary: (p: SubjectPhoto) => void;
  onCropPhoto: (p: SubjectPhoto) => void;
  onTracePhoto: (p: SubjectPhoto) => void;
  onDeleteSubject: () => void;
  onDropFiles: (files: File[]) => void;
  onUploadFiles: (files: File[]) => void;
}) {
  /* 名称内联编辑 */
  const [renaming, setRenaming] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  /* 标签编辑 */
  const [tagDraft, setTagDraft] = useState("");
  /* 拖拽扩充 */
  const [dragOver, setDragOver] = useState(false);
  const dragDepthRef = useRef(0);
  /* 上传 input ref */
  const fileInputRef = useRef<HTMLInputElement>(null);

  const startRename = () => { setNameDraft(subject.name); setRenaming(true); };
  const commitRename = () => {
    const n = nameDraft.trim();
    setRenaming(false);
    if (n && n !== subject.name) onRename(n);
  };
  const addTag = () => {
    const v = tagDraft.trim();
    if (v && !subject.tags.includes(v)) onTagsChange([...subject.tags, v]);
    setTagDraft("");
  };

  /* 拖拽接收：本地图片扩充底库 */
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragOver(false);
    const files = Array.from(e.dataTransfer?.files ?? []).filter((f) => f.type.startsWith("image/"));
    if (files.length) onDropFiles(files);
  };

  return (
    <div className="flex-1 min-w-0 case-card flex flex-col min-h-0">
      {/* 详情头：名称/标签 + 上传 */}
      <div className="px-4 py-3 border-b border-gray-100 shrink-0">
        {/* 第一行：名称 + 上传按钮 */}
        <div className="flex items-center gap-2">
          <div className="flex-1 min-w-0">
            {renaming ? (
              <input autoFocus className="g-input !h-[28px] !text-[14px] font-semibold !w-[240px]"
                value={nameDraft} onChange={(e) => setNameDraft(e.target.value)}
                onBlur={commitRename}
                onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setRenaming(false); }} />
            ) : (
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[15px] font-bold text-gray-900 truncate">{subject.name}</span>
                <button className="p-1 rounded text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors shrink-0" title="重命名" onClick={startRename}>
                  <IconPencil />
                </button>
                <span className={"text-[10.5px] px-1.5 py-0.5 rounded-full shrink-0 " + (subject.kind === "person" ? "bg-blue-50 text-blue-600" : "bg-amber-50 text-amber-600")}>
                  {KIND_LABEL[subject.kind]}
                </span>
              </div>
            )}
          </div>
          <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden"
            onChange={(e) => { const files = Array.from(e.target.files ?? []).filter((f) => f.type.startsWith("image/")); if (files.length) onUploadFiles(files); e.target.value = ""; }} />
          <button className="g-btn g-btn-primary !h-[28px] !text-[12px] shrink-0"
            onClick={() => fileInputRef.current?.click()}>
            <IconPlus /> 上传
          </button>
        </div>
        {/* 第二行：标签（与上传按钮同高对齐） */}
        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap min-w-0">
          {subject.tags.map((t) => (
            <span key={t} className="inline-flex items-center gap-1 text-[10.5px] px-1.5 py-px rounded-full bg-red-50 text-red-500">
              {t}
              <button className="hover:text-red-700" onClick={() => onTagsChange(subject.tags.filter((x) => x !== t))} title="移除标签">×</button>
            </span>
          ))}
          <input
            className="text-[10.5px] w-[80px] px-1.5 py-px rounded border border-transparent focus:border-[#4f7cff] focus:w-[120px] outline-none placeholder:text-transparent focus:placeholder:text-gray-300 transition-all duration-200"
            placeholder="+ 添加标签" value={tagDraft}
            onChange={(e) => setTagDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addTag(); }}
          />
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto relative"
        onDragEnter={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          e.preventDefault(); dragDepthRef.current += 1; setDragOver(true);
        }}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={() => { dragDepthRef.current = Math.max(0, dragDepthRef.current - 1); if (dragDepthRef.current === 0) setDragOver(false); }}
        onDrop={onDrop}
      >
        <div className="relative p-4">
          {photos.length === 0 ? (
            <div className="g-empty !py-16"><IconPerson /><span>暂无底库照片，拖拽图片或点击「上传」扩充</span></div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-2.5">
              {photos.map((p) => (
                <div key={p.id} className="group relative aspect-square bg-gray-50 rounded-lg overflow-hidden border border-gray-100 hover:border-gray-300 transition-colors">
                  <CroppedPhoto url={subjectPhotoUrl(subject.id, p.id)} crop={p.crop} />
                  {p.is_primary && (
                    <span className="absolute left-1.5 top-1.5 text-[9.5px] px-1.5 py-px rounded-full bg-[#4f7cff] text-white shadow">主图</span>
                  )}
                  {p.source && (
                    <span className="absolute right-1.5 top-1.5 text-[9px] px-1.5 py-px rounded-full bg-black/50 text-white/90">
                      {p.source === "upload" ? "上传" : p.source === "case" ? "案例库" : p.source === "track" ? "检测" : "图搜"}
                    </span>
                  )}
                  {/* hover 操作层 */}
                  <div className="absolute inset-0 bg-black/45 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1.5">
                    <button className="px-2 py-1 rounded bg-white/90 text-[11px] text-gray-700 hover:bg-white" title="裁剪（对齐人脸/车牌区域）"
                      onClick={() => onCropPhoto(p)}>裁剪</button>
                    {!p.is_primary && (
                      <button className="px-2 py-1 rounded bg-white/90 text-[11px] text-gray-700 hover:bg-white" onClick={() => onSetPrimary(p)}>设为主图</button>
                    )}
                    {p.source_video_id && (
                      <button className="px-2 py-1 rounded bg-[#4f7cff] text-[11px] text-white hover:bg-[#4369f5]" title="溯源到原始视频"
                        onClick={() => onTracePhoto(p)}>溯源</button>
                    )}
                    <button className="p-1.5 rounded bg-red-500 text-white hover:bg-red-600" title="删除"
                      onClick={() => onDeletePhoto(p)}><IconTrash /></button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 拖拽覆盖层 */}
        {dragOver && (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-[#0b0f16]/60 backdrop-blur-sm rounded-lg pointer-events-none">
            <div className="text-white/90 text-[13px] px-4 py-2 rounded-lg border border-dashed border-[#4f7cff] bg-[#0b0f16]/70">
              松开扩充「{subject.name}」底库
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════ 裁剪弹窗 ═══════════════════ */
function CropDialog({ subjectId, photo, onClose, onSaved }: {
  subjectId: string; photo: SubjectPhoto; onClose: () => void; onSaved: () => void;
}) {
  const url = subjectPhotoUrl(subjectId, photo.id);
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  /* 裁剪矩形（显示坐标系 px），图片加载后按展示框换算 */
  const [rect, setRect] = useState<Crop | null>(null);
  const [saving, setSaving] = useState(false);
  const dragRef = useRef<null | { mode: "draw" | "move" | "resize"; startX: number; startY: number; orig: Crop }>(null);

  /* 图片加载后按展示框换算：box = 缩放后的渲染尺寸（fit 最大 640×420） */
  const onImgLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const el = e.target as HTMLImageElement;
    const nw = el.naturalWidth, nh = el.naturalHeight;
    if (!nw || !nh) return;
    const maxW = 640, maxH = 420;
    const scale = Math.min(1, maxW / nw, maxH / nh);
    const w = Math.round(nw * scale), h = Math.round(nh * scale);
    setBox({ w, h });
    /* 已有裁剪：归一化 → 显示坐标；否则默认中央 70% */
    if (photo.crop) {
      setRect({ x1: photo.crop.x1 * w, y1: photo.crop.y1 * h, x2: photo.crop.x2 * w, y2: photo.crop.y2 * h });
    } else {
      setRect({ x1: w * 0.15, y1: h * 0.15, x2: w * 0.85, y2: h * 0.85 });
    }
  };

  const norm = (r: Crop): Crop => {
    const b = box!;
    const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
    return {
      x1: clamp(Math.min(r.x1, r.x2), 0, b.w) / b.w,
      y1: clamp(Math.min(r.y1, r.y2), 0, b.h) / b.h,
      x2: clamp(Math.max(r.x1, r.x2), 0, b.w) / b.w,
      y2: clamp(Math.max(r.y1, r.y2), 0, b.h) / b.h,
    };
  };

  const onMouseDown = (e: React.MouseEvent) => {
    if (!box) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    if (rect && x >= rect.x1 - 6 && x <= rect.x2 + 6 && y >= rect.y1 - 6 && y <= rect.y2 + 6) {
      /* 右下角手柄：resize；矩形内：move */
      const atHandle = Math.abs(x - rect.x2) < 12 && Math.abs(y - rect.y2) < 12;
      dragRef.current = { mode: atHandle ? "resize" : "move", startX: e.clientX, startY: e.clientY, orig: { ...rect } };
    } else {
      /* 空白处：新画 */
      dragRef.current = { mode: "draw", startX: e.clientX, startY: e.clientY, orig: { x1: x, y1: y, x2: x, y2: y } };
    }
  };
  const onMouseMove = (e: React.MouseEvent) => {
    const d = dragRef.current;
    if (!d || !box) return;
    const r = e.currentTarget.getBoundingClientRect();
    const dx = e.clientX - d.startX, dy = e.clientY - d.startY;
    if (d.mode === "draw") setRect({ x1: d.orig.x1, y1: d.orig.y1, x2: d.orig.x1 + dx, y2: d.orig.y1 + dy });
    else if (d.mode === "move") setRect({ ...d.orig, x1: d.orig.x1 + dx, y1: d.orig.y1 + dy, x2: d.orig.x2 + dx, y2: d.orig.y2 + dy });
    else setRect({ ...d.orig, x2: d.orig.x2 + dx, y2: d.orig.y2 + dy });
  };
  const onMouseUp = () => { dragRef.current = null; };

  const save = async () => {
    if (!box || !rect || saving) return;
    setSaving(true);
    try {
      await subjectsApi.updateSubjectPhoto(subjectId, photo.id, { crop: norm(rect) });
      onSaved();
      onClose();
    } catch (err) {
      alert(err instanceof Error ? err.message : "保存失败");
    } finally { setSaving(false); }
  };

  const clearCrop = async () => {
    setSaving(true);
    try {
      await subjectsApi.updateSubjectPhoto(subjectId, photo.id, { crop: null });
      onSaved();
      onClose();
    } catch (err) {
      alert(err instanceof Error ? err.message : "保存失败");
    } finally { setSaving(false); }
  };

  return createPortal(
    <div className="g-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="g-modal" style={{ width: 700 }}>
        <div className="g-card-hd">
          <span className="g-card-tt">裁剪底图（对齐人脸 / 车牌区域）</span>
          <button className="modal-x" onClick={onClose} title="关闭" aria-label="关闭">×</button>
        </div>
        <div className="p-4">
          <div
            className="relative mx-auto select-none"
            style={box
              ? { width: box.w, height: box.h, cursor: rect ? "move" : "crosshair", touchAction: "none" }
              : { width: 640, height: 420 }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
          >
            <img src={url} alt="" draggable={false} onLoad={onImgLoad}
              style={box ? { width: box.w, height: box.h, objectFit: "fill" } : { maxWidth: 640, maxHeight: 420, opacity: 0.4 }} />
            {box && rect && (
              <>
                {/* 暗色遮罩（裁剪区外） */}
                <div className="absolute" style={{ top: 0, left: 0, right: 0, height: rect.y1, background: "rgba(0,0,0,0.55)" }} />
                <div className="absolute" style={{ top: rect.y2, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.55)" }} />
                <div className="absolute" style={{ top: rect.y1, left: 0, width: rect.x1, height: rect.y2 - rect.y1, background: "rgba(0,0,0,0.55)" }} />
                <div className="absolute" style={{ top: rect.y1, left: rect.x2, right: 0, height: rect.y2 - rect.y1, background: "rgba(0,0,0,0.55)" }} />
                {/* 裁剪框 */}
                <div className="absolute border-2 border-[#4f7cff] pointer-events-none"
                  style={{ left: rect.x1, top: rect.y1, width: rect.x2 - rect.x1, height: rect.y2 - rect.y1 }} />
                {/* 右下角手柄 */}
                <div className="absolute w-3 h-3 bg-white border-2 border-[#4f7cff] rounded-sm"
                  style={{ left: rect.x2 - 6, top: rect.y2 - 6 }} />
              </>
            )}
            {!box && <div className="absolute inset-0 flex items-center justify-center text-gray-400 text-sm pointer-events-none">加载图片…</div>}
            {box && !rect && <div className="absolute inset-0 flex items-center justify-center text-white/80 text-[12px] pointer-events-none">在图片上按住拖动框选目标区域</div>}
          </div>
          {rect && (
            <div className="mt-2 text-[11px] text-gray-400 text-center">
              拖动矩形移动 · 拖动右下角手柄缩放 · 框外按住拖动重新框选
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-gray-100">
          {rect && (
            <button className="g-btn mr-auto" onClick={() => void clearCrop()} disabled={saving} title="取消裁剪，恢复整图显示">取消裁剪</button>
          )}
          <button className="g-btn" onClick={onClose} disabled={saving}>取消</button>
          <button className="g-btn g-btn-primary" onClick={() => void save()} disabled={saving || !rect}>
            {saving ? "保存中…" : "保存裁剪"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ═══════════════════ 新建目标弹窗 ═══════════════════ */
function NewSubjectDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [kind, setKind] = useState<ImageSubjectKind>("person");
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [mainFile, setMainFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onPick = (f: File | null) => {
    setPreview((prev) => { if (prev) URL.revokeObjectURL(prev); return f ? URL.createObjectURL(f) : null; });
    setMainFile(f);
  };

  const create = async () => {
    if (busy) return;
    if (!name.trim()) { alert("请填写目标名称"); return; }
    setBusy(true);
    try {
      const subject = await subjectsApi.createImageSubject({
        kind,
        name: name.trim(),
        tags: tags.split(/[,，\s]+/).map((t) => t.trim()).filter(Boolean),
      });
      if (mainFile) {
        try { await subjectsApi.uploadSubjectPhoto(subject.id, [mainFile], "upload"); } catch { /* 主图失败不阻断 */ }
      }
      onCreated(subject.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "创建失败");
    } finally { setBusy(false); }
  };

  return createPortal(
    <div className="g-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="g-modal" style={{ width: 460 }}>
        <div className="g-card-hd">
          <span className="g-card-tt"><IconPlus /> 新建目标</span>
          <button className="modal-x" onClick={onClose} title="关闭" aria-label="关闭">×</button>
        </div>
        <div className="p-5 space-y-3.5">
          {/* 类型 */}
          <div>
            <label className="g-label">目标类型</label>
            <div className="flex gap-1.5">
              {([["person", "人"], ["other", "其他"]] as [ImageSubjectKind, string][]).map(([k, label]) => (
                <button key={k} type="button"
                  className={"flex-1 h-[34px] rounded-lg border text-[13px] font-medium transition-colors " +
                    (kind === k ? "border-[#4f7cff] bg-[#4f7cff]/5 text-[#4f7cff]" : "border-gray-200 text-gray-500 hover:border-gray-300")}
                  onClick={() => setKind(k)}>{label}</button>
              ))}
            </div>
          </div>
          {/* 名称 */}
          <div>
            <label className="g-label">名称 <span style={{ color: "#ef4444" }}>*</span></label>
            <input className="g-input w-full" placeholder={kind === "person" ? "如：嫌疑人张三" : "如：套牌车·京A12345"} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          {/* 标签 */}
          <div>
            <label className="g-label">标签（逗号分隔）</label>
            <input className="g-input w-full" placeholder="如：在逃, 重点" value={tags} onChange={(e) => setTags(e.target.value)} />
          </div>
          {/* 主图 */}
          <div>
            <label className="g-label">主图（可选）</label>
            <div className="flex items-center gap-2.5">
              <label className="flex-1 h-[120px] rounded-lg border-2 border-dashed border-gray-200 hover:border-[#4f7cff]/50 flex flex-col items-center justify-center gap-1 cursor-pointer bg-gray-50/50 overflow-hidden">
                {preview ? (
                  <img src={preview} alt="" className="w-full h-full object-contain" />
                ) : (
                  <>
                    <span className="text-gray-300"><IconPlus /></span>
                    <span className="text-[11.5px] text-gray-400">点击选择底图</span>
                  </>
                )}
                <input type="file" accept="image/*" hidden onChange={(e) => { onPick(e.target.files?.[0] ?? null); e.target.value = ""; }} />
              </label>
              {mainFile && (
                <button className="g-btn !px-2.5" onClick={() => onPick(null)}>移除</button>
              )}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-gray-100">
          <button className="g-btn" onClick={onClose} disabled={busy}>取消</button>
          <button className="g-btn g-btn-primary" onClick={() => void create()} disabled={busy}>
            {busy ? "创建中…" : "创建目标"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/* ═══════════════════ 页面编排 ═══════════════════ */
export function ImageLibrary() {
  const { openWorkbench, openImageLibrary, imageLibIntent, consumeImageLibIntent, clearImageLibAlerts } = useApp();

  const [subjects, setSubjects] = useState<ImageSubject[]>([]);
  const [search, setSearch] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subject, setSubject] = useState<ImageSubject | null>(null);
  const [photos, setPhotos] = useState<SubjectPhoto[]>([]);

  const [showNew, setShowNew] = useState(false);
  const [cropPhoto, setCropPhoto] = useState<SubjectPhoto | null>(null);

  /* ── 列表加载：5s 轮询（与全局 1.5s/4s 节奏一致，列表轻量） ── */
  const loadSubjects = useCallback(() => {
    subjectsApi.listImageSubjects({ search: search.trim() || undefined })
      .then((data) => setSubjects(data ?? []))
      .catch(() => {});
  }, [search]);

  useEffect(() => { loadSubjects(); }, [loadSubjects]);
  useEffect(() => {
    const iv = setInterval(loadSubjects, 5000);
    return () => clearInterval(iv);
  }, [loadSubjects]);

  /* ── 默认选中第一个目标 ── */
  useEffect(() => {
    if (!selectedId && subjects.length > 0) setSelectedId(subjects[0].id);
  }, [subjects, selectedId]);

  /* ── 跨页跳转意图（openImageLibrary({subjectId})）一次性消费 ── */
  useEffect(() => {
    if (!imageLibIntent) return;
    if (imageLibIntent.subjectId) setSelectedId(imageLibIntent.subjectId);
    consumeImageLibIntent();
    /* 进入素材库即视为已读告警（下一阶段红点清零） */
    clearImageLibAlerts();
  }, [imageLibIntent, consumeImageLibIntent, clearImageLibAlerts]);

  /* ── 详情加载：选中目标 → 目标 + 底图，5s 轮询 ── */
  useEffect(() => {
    if (!selectedId) { setSubject(null); setPhotos([]); return; }
    let cancelled = false;
    const loadAll = () => {
      subjectsApi.getImageSubject(selectedId).then((s) => { if (!cancelled) setSubject(s); }).catch(() => {});
      subjectsApi.listSubjectPhotos(selectedId).then((p) => { if (!cancelled) setPhotos(p ?? []); }).catch(() => {});
    };
    loadAll();
    const iv = setInterval(loadAll, 5000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [selectedId]);

  /* ── 操作 ── */
  const renameSubject = async (name: string) => {
    if (!subject) return;
    try { await subjectsApi.updateImageSubject(subject.id, { name }); setSubject({ ...subject, name }); loadSubjects(); }
    catch (err) { alert(err instanceof Error ? err.message : "重命名失败"); }
  };
  const changeTags = async (tgs: string[]) => {
    if (!subject) return;
    try { await subjectsApi.updateImageSubject(subject.id, { tags: tgs }); setSubject({ ...subject, tags: tgs }); loadSubjects(); }
    catch (err) { alert(err instanceof Error ? err.message : "保存标签失败"); }
  };
  const deleteSubject = async () => {
    if (!subject) return;
    if (!window.confirm(`确认删除目标「${subject.name}」及其全部底图？不可恢复。`)) return;
    try {
      await subjectsApi.deleteImageSubject(subject.id);
      setSelectedId(null);
      setSubject(null); setPhotos([]);
      loadSubjects();
    } catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };
  const deletePhoto = async (p: SubjectPhoto) => {
    if (!subject) return;
    if (!window.confirm("确认删除该底图？")) return;
    try { await subjectsApi.deleteSubjectPhoto(subject.id, p.id); setPhotos((prev) => prev.filter((x) => x.id !== p.id)); loadSubjects(); }
    catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };
  const setPrimary = async (p: SubjectPhoto) => {
    if (!subject) return;
    try {
      await subjectsApi.updateSubjectPhoto(subject.id, p.id, { is_primary: true });
      setPhotos((prev) => prev.map((x) => ({ ...x, is_primary: x.id === p.id })));
      loadSubjects();
    } catch (err) { alert(err instanceof Error ? err.message : "设置失败"); }
  };
  const onDropFiles = async (files: File[]) => {
    if (!subject) return;
    try {
      const added = await subjectsApi.uploadSubjectPhoto(subject.id, files, "upload");
      setPhotos((prev) => [...prev, ...added]);
      loadSubjects();
    } catch (err) { alert(err instanceof Error ? err.message : "上传失败"); }
  };
  const tracePhoto = (p: SubjectPhoto) => {
    if (!p.source_video_id) return;
    openWorkbench(p.source_video_id, { versionId: p.source_video_id });
  };

  return (
    <div className="h-full flex flex-col gap-2 p-2">
      <IlHeader onNew={() => setShowNew(true)} />

      <div className="flex flex-1 gap-2 min-h-0">
        <IlSide
          subjects={subjects} search={search} setSearch={setSearch}
          selectedId={selectedId} onSelect={setSelectedId} onDelete={deleteSubject}
        />

        {subject ? (
          <IlDetail
            subject={subject} photos={photos}
            onRename={(n) => void renameSubject(n)}
            onTagsChange={(t) => void changeTags(t)}
            onDeletePhoto={(p) => void deletePhoto(p)}
            onSetPrimary={(p) => void setPrimary(p)}
            onCropPhoto={setCropPhoto}
            onTracePhoto={(p) => tracePhoto(p)}
            onDeleteSubject={() => void deleteSubject()}
            onDropFiles={(files) => void onDropFiles(files)}
            onUploadFiles={(files) => void onDropFiles(files)}
          />
        ) : (
          <div className="flex-1 min-w-0 case-card flex flex-col min-h-0">
            <div className="g-empty flex-1">
              <IconPerson />
              <span>选择左侧目标查看详情，或点击「新建目标」</span>
            </div>
          </div>
        )}
      </div>

      {/* 新建目标 */}
      {showNew && (
        <NewSubjectDialog
          onClose={() => setShowNew(false)}
          onCreated={(id) => { setShowNew(false); setSelectedId(id); loadSubjects(); }}
        />
      )}

      {/* 裁剪 */}
      {cropPhoto && subject && (
        <CropDialog
          subjectId={subject.id} photo={cropPhoto}
          onClose={() => setCropPhoto(null)}
          onSaved={() => {
            subjectsApi.listSubjectPhotos(subject.id).then((p) => setPhotos(p ?? [])).catch(() => {});
          }}
        />
      )}
    </div>
  );
}
