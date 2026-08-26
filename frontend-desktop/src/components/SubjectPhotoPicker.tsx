import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useDisableVideoInteraction } from "../hooks/useDisableVideoInteraction";
import { subjectsApi, subjectPhotoUrl, subjectPrimaryUrl } from "../mocks/subjectsMock";
import type { ImageSubject, SubjectPhoto } from "../types";
import { IconPerson, IconCar, IconSearch } from "./icons";

const KIND_LABEL: Record<string, string> = { person: "人", other: "其他" };

/* 从素材库（关注目标底库）选择一张底图作为图搜/人脸搜的查询图。
   左侧目标列表 + 搜索栏，右侧底库照片网格。替代已退役的 CaseAssetPicker。 */

export function SubjectPhotoPicker({
  onSelect,
  onClose,
}: {
  onSelect: (file: File) => void;
  onClose: () => void;
}) {
  useDisableVideoInteraction();
  const [subjects, setSubjects] = useState<ImageSubject[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [photos, setPhotos] = useState<SubjectPhoto[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingPhotos, setLoadingPhotos] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetchingId, setFetchingId] = useState<string | null>(null);

  // 加载目标列表
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const list = await subjectsApi.listImageSubjects({});
        if (!cancelled) {
          setSubjects(list);
          // 自动选中第一个
          if (list.length > 0) setSelectedId(list[0].id);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载素材库失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 选中目标变化时加载其照片
  useEffect(() => {
    if (!selectedId) { setPhotos([]); return; }
    let cancelled = false;
    (async () => {
      setLoadingPhotos(true);
      try {
        const list = await subjectsApi.listSubjectPhotos(selectedId);
        if (!cancelled) setPhotos(list);
      } catch {
        if (!cancelled) setPhotos([]);
      } finally {
        if (!cancelled) setLoadingPhotos(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  // 搜索过滤
  const filtered = useMemo(() => {
    if (!search.trim()) return subjects;
    const q = search.trim().toLowerCase();
    return subjects.filter(
      (s) => s.name.toLowerCase().includes(q) || s.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [subjects, search]);

  const selectedSubject = subjects.find((s) => s.id === selectedId) ?? null;

  const pick = async (subject: ImageSubject, photo: SubjectPhoto) => {
    setFetchingId(photo.id);
    try {
      const res = await fetch(subjectPhotoUrl(subject.id, photo.id));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const file = new File([blob], `${subject.name}.jpg`, { type: blob.type || "image/jpeg" });
      onSelect(file);
    } catch (err) {
      alert(err instanceof Error ? err.message : "获取图片失败");
    } finally {
      setFetchingId(null);
    }
  };

  return createPortal(
    <div className="fixed inset-0 flex items-center justify-center bg-black/40"
      style={{ zIndex: 2147483000, transform: "translateZ(0)", pointerEvents: "auto" }}>
      <div className="w-[720px] max-w-[90vw] h-[520px] max-h-[80vh] bg-white rounded-xl shadow-2xl flex flex-col">
        {/* 标题栏 */}
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between shrink-0">
          <span className="text-[14px] font-bold text-gray-800">从素材库选图</span>
          <button className="text-gray-400 hover:text-gray-600" onClick={onClose}>✕</button>
        </div>

        {/* 主体：左侧目标列表 + 右侧照片网格 */}
        <div className="flex-1 flex min-h-0">
          {/* 左侧目标列表 */}
          <div className="w-[220px] shrink-0 border-r border-gray-100 flex flex-col min-h-0">
            {/* 搜索栏 */}
            <div className="px-2.5 pt-2.5 pb-2 shrink-0">
              <div className="relative">
                <input
                  className="g-input w-full !h-[28px] !text-[11px] !pl-7" placeholder="搜索名称 / 标签"
                  value={search} onChange={(e) => setSearch(e.target.value)}
                />
                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400"><IconSearch /></span>
              </div>
            </div>

            {/* 目标列表 */}
            <div className="flex-1 overflow-auto py-1">
              {loading && <div className="py-8 text-center text-[11px] text-gray-400">加载中…</div>}
              {!loading && filtered.length === 0 && (
                <div className="py-8 text-center text-[11px] text-gray-400">暂无目标</div>
              )}
              {!loading && filtered.map((s) => {
                const active = s.id === selectedId;
                const cnt = s.photo_count ?? 0;
                return (
                  <div key={s.id}
                    className={"mx-1.5 px-2.5 py-2 rounded-md cursor-pointer border-l-[3px] transition-all duration-150 " +
                      (active ? "bg-brand/5 border-[#4f7cff] shadow-sm" : "border-transparent hover:bg-white hover:shadow-sm")}
                    onClick={() => setSelectedId(s.id)}
                  >
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-md overflow-hidden shrink-0 bg-gray-50 flex items-center justify-center">
                        {cnt > 0 ? (
                          <img src={subjectPrimaryUrl(s.id)} alt="" className="w-full h-full object-cover"
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                        ) : null}
                        <span className={"text-gray-300 " + (cnt > 0 ? "hidden" : "")}>
                          {s.kind === "person" ? <IconPerson /> : <IconCar />}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1">
                          <span className={"text-[12px] truncate " + (active ? "text-[#4f7cff] font-semibold" : "text-gray-800")}>{s.name}</span>
                          <span className={"shrink-0 text-[9px] px-1 rounded-full " + (s.kind === "person" ? "bg-blue-50 text-blue-600" : "bg-amber-50 text-amber-600")}>
                            {KIND_LABEL[s.kind]}
                          </span>
                        </div>
                        <span className="text-[10px] text-gray-400 font-mono">{cnt} 张</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 右侧照片网格 */}
          <div className="flex-1 flex flex-col min-h-0 min-w-0">
            {/* 目标标题 */}
            <div className="px-3 py-2 border-b border-gray-50 shrink-0">
              {selectedSubject ? (
                <span className="text-[12px] text-gray-600">
                  <span className="font-medium text-gray-800">{selectedSubject.name}</span>
                  <span className="ml-1.5 text-gray-400">· {photos.length} 张底图</span>
                </span>
              ) : (
                <span className="text-[12px] text-gray-400">请选择左侧目标</span>
              )}
            </div>

            {/* 照片网格 */}
            <div className="flex-1 overflow-auto p-3">
              {!selectedSubject && (
                <div className="py-12 text-center text-[12px] text-gray-400">请从左侧选择一个目标</div>
              )}
              {selectedSubject && loadingPhotos && (
                <div className="py-12 text-center text-[12px] text-gray-400">加载照片中…</div>
              )}
              {selectedSubject && !loadingPhotos && photos.length === 0 && (
                <div className="py-12 text-center text-[12px] text-gray-400">该目标暂无底图</div>
              )}
              {selectedSubject && !loadingPhotos && photos.length > 0 && (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {photos.map((photo) => (
                    <button
                      key={photo.id}
                      disabled={fetchingId != null}
                      onClick={() => pick(selectedSubject, photo)}
                      className="group relative aspect-square rounded-lg overflow-hidden border border-gray-200 hover:border-[#4f7cff] disabled:opacity-60 transition-colors"
                    >
                      <img
                        src={subjectPhotoUrl(selectedSubject.id, photo.id)}
                        alt=""
                        loading="lazy"
                        className="w-full h-full object-cover"
                        onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.15"; }}
                      />
                      {photo.is_primary && (
                        <span className="absolute top-1 left-1 px-1 py-px rounded bg-[#4f7cff]/80 text-white text-[9px]">主图</span>
                      )}
                      {fetchingId === photo.id && (
                        <span className="absolute inset-0 flex items-center justify-center bg-black/40 text-white text-[11px]">选取中…</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
