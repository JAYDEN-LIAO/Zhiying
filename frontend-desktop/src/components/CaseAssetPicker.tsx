import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { CaseAssetItem } from "../types";

/* 从案例素材（case_assets）中选择一张图片作为图搜/人脸搜的查询图。
   选中后抓取原图字节构造 File，回传给调用方发起搜索。 */

export function CaseAssetPicker({
  groupId,
  groupName,
  onSelect,
  onClose,
}: {
  groupId: string;
  groupName?: string;
  onSelect: (file: File, asset: CaseAssetItem) => void;
  onClose: () => void;
}) {
  const [images, setImages] = useState<CaseAssetItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchingId, setFetchingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getGroupAssets(groupId)
      .then((d) => { if (!cancelled) setImages(d?.images ?? []); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "加载案例素材失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [groupId]);

  const pick = async (asset: CaseAssetItem) => {
    setFetchingId(asset.id);
    try {
      const res = await fetch(api.getAssetFileUrl(groupId, asset.id));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const mime = blob.type || (asset.file_ext ? `image/${asset.file_ext.replace(/^\./, "")}` : "image/*");
      const file = new File([blob], asset.name || `asset${asset.file_ext || ".png"}`, { type: mime });
      onSelect(file, asset);
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
          <span className="text-[14px] font-bold text-gray-800">
            从案例素材选图{groupName ? ` · ${groupName}` : ""}
          </span>
          <button className="text-gray-400 hover:text-gray-600" onClick={onClose}>✕</button>
        </div>
        <div className="flex-1 overflow-auto p-3">
          {loading && <div className="py-8 text-center text-[12px] text-gray-400">加载中…</div>}
          {!loading && error && <div className="py-8 text-center text-[12px] text-red-500">{error}</div>}
          {!loading && !error && images.length === 0 && (
            <div className="py-8 text-center text-[12px] text-gray-400">该案例暂无图片素材，请先在案例库上传图片。</div>
          )}
          {!loading && !error && images.length > 0 && (
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              {images.map((img) => (
                <button
                  key={img.id}
                  disabled={fetchingId != null}
                  onClick={() => pick(img)}
                  className="group relative aspect-square rounded-lg overflow-hidden border border-gray-200 hover:border-[#4f7cff] disabled:opacity-60 transition-colors"
                  title={img.name}
                >
                  <img
                    src={api.getAssetFileUrl(groupId, img.id)}
                    alt=""
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.15"; }}
                  />
                  <span className="absolute inset-x-0 bottom-0 px-1 py-0.5 bg-black/45 text-white text-[10px] truncate text-left">
                    {img.name}
                  </span>
                  {fetchingId === img.id && (
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