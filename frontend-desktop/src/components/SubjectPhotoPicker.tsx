import { useEffect, useState } from "react";
import { subjectsApi, subjectPhotoUrl } from "../mocks/subjectsMock";
import type { ImageSubject, SubjectPhoto } from "../types";

/* 从素材库（关注目标底库）选择一张底图作为图搜/人脸搜的查询图。
   平铺展示所有目标的底库照片（带目标名标签），选中后抓取原图字节
   构造 File 回传给调用方发起搜索。替代已退役的 CaseAssetPicker。 */

export function SubjectPhotoPicker({
  onSelect,
  onClose,
}: {
  onSelect: (file: File) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<Array<{ subject: ImageSubject; photo: SubjectPhoto }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchingId, setFetchingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const subjects = await subjectsApi.listImageSubjects({});
        const rows: Array<{ subject: ImageSubject; photo: SubjectPhoto }> = [];
        for (const s of subjects) {
          const photos = await subjectsApi.listSubjectPhotos(s.id);
          for (const p of photos) rows.push({ subject: s, photo: p });
        }
        if (!cancelled) setItems(rows);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载素材库失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[640px] max-w-[90vw] max-h-[80vh] bg-white rounded-xl shadow-2xl flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between shrink-0">
          <span className="text-[14px] font-bold text-gray-800">从素材库选图</span>
          <button className="text-gray-400 hover:text-gray-600" onClick={onClose}>✕</button>
        </div>
        <div className="flex-1 overflow-auto p-3">
          {loading && <div className="py-8 text-center text-[12px] text-gray-400">加载中…</div>}
          {!loading && error && <div className="py-8 text-center text-[12px] text-red-500">{error}</div>}
          {!loading && !error && items.length === 0 && (
            <div className="py-8 text-center text-[12px] text-gray-400">素材库暂无底图，请先在素材库添加目标与照片。</div>
          )}
          {!loading && !error && items.length > 0 && (
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              {items.map(({ subject, photo }) => (
                <button
                  key={photo.id}
                  disabled={fetchingId != null}
                  onClick={() => pick(subject, photo)}
                  className="group relative aspect-square rounded-lg overflow-hidden border border-gray-200 hover:border-[#4f7cff] disabled:opacity-60 transition-colors"
                  title={subject.name}
                >
                  <img
                    src={subjectPhotoUrl(subject.id, photo.id)}
                    alt=""
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.15"; }}
                  />
                  <span className="absolute inset-x-0 bottom-0 px-1 py-0.5 bg-black/45 text-white text-[10px] truncate text-left">
                    {subject.name}
                  </span>
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
  );
}
