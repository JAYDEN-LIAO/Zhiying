import { useEffect, useMemo, useState } from "react";
import { api, downloadFile } from "../../services/api";
import { isMockId } from "../../services/mock";
import { formatSec } from "../../utils/helpers";
import { colorOf, zh } from "../../labels";
import { IconChevronDown, IconDownload, IconPlus, IconTarget, IconVideo } from "../icons";
import type { DetectionData, FaceData, Track, VideoResponse } from "../../types";

/* ════════════════════════════════════════════════════════════
   DetectionPanel — 物体检测（左下面板，列表流）
   标题栏右侧：类别筛选下拉「全部 · N」
   行卡片：缩略图 + 类别名(#序号) + 身份标签(紫) + 时间段
          + 关注按钮(+) + 导出缩略图按钮
   点击行 → 定位到该目标出现时刻
   ════════════════════════════════════════════════════════════ */

export function DetectionPanel({
  video,
  detections,
  onSeek,
}: {
  video: VideoResponse | null;
  detections: DetectionData | null;
  onSeek: (sec: number) => void;
}) {
  const [filterCls, setFilterCls] = useState<string | null>(null); // null = 全部
  const [filterOpen, setFilterOpen] = useState(false);
  const [watched, setWatched] = useState<Set<number>>(new Set());
  const [identityByTrack, setIdentityByTrack] = useState<Map<number, string>>(new Map());

  const tracks = useMemo(() => detections?.tracks ?? [], [detections]);
  /* 类别 → 数量（保持出现顺序） */
  const clsCounts = useMemo(() => {
    const order: string[] = [];
    const map = new Map<string, number>();
    for (const t of tracks) {
      if (!map.has(t.class_name)) order.push(t.class_name);
      map.set(t.class_name, (map.get(t.class_name) ?? 0) + 1);
    }
    return order.map((cls) => ({ cls, count: map.get(cls)! }));
  }, [tracks]);

  const visible = useMemo(
    () => (filterCls ? tracks.filter((t) => t.class_name === filterCls) : tracks),
    [tracks, filterCls],
  );

  /* 人脸身份标签（person track → "人物 A"；未开启人脸/无数据时为空） */
  useEffect(() => {
    if (!video || video.status !== "completed" || !video.face_enabled) {
      setIdentityByTrack(new Map());
      return;
    }
    let cancelled = false;
    api
      .fetchFaceData(video.id)
      .then((d: FaceData) => {
        if (cancelled) return;
        const m = new Map<number, string>();
        const idToLabel = new Map((d.identities ?? []).map((i) => [i.id, i.label]));
        for (const [tid, { identity_id }] of Object.entries(d.track_to_identity ?? {})) {
          const label = idToLabel.get(identity_id);
          if (label) m.set(Number(tid), label);
        }
        setIdentityByTrack(m);
      })
      .catch(() => {
        if (!cancelled) setIdentityByTrack(new Map());
      });
    return () => {
      cancelled = true;
    };
  }, [video?.id, video?.status, video?.face_enabled]);

  const toggleWatch = (trackId: number) => {
    setWatched((prev) => {
      const next = new Set(prev);
      if (next.has(trackId)) next.delete(trackId);
      else next.add(trackId);
      return next;
    });
  };

  /* 导出该轨迹的最佳截图 */
  const exportThumb = async (track: Track) => {
    if (!video) return;
    if (isMockId(video.id)) {
      alert("演示模式暂不支持导出，接入后端后可导出轨迹截图");
      return;
    }
    try {
      const blob = await api.exportTrackThumbnail(video.id, track.track_id);
      downloadFile(blob, `${zh(track.class_name)}_${track.display_seq ?? track.track_id}.jpg`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "导出失败");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-card bg-card-bg shadow-card">
      {/* 标题栏 + 筛选下拉 */}
      <div className="relative flex shrink-0 items-center justify-between border-b border-border-light px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-primary"><IconTarget /></span>
          <p className="text-sm font-semibold text-gray-700">物体检测</p>
        </div>
        <div className="relative">
          <button
            onClick={() => setFilterOpen((v) => !v)}
            className="flex items-center gap-1 rounded-lg border border-border-light bg-surface px-2.5 py-1 text-xs text-gray-600 transition-colors hover:border-primary/50"
          >
            {filterCls ? `${zh(filterCls)} · ${clsCounts.find((c) => c.cls === filterCls)?.count ?? 0}` : `全部 · ${tracks.length}`}
            <IconChevronDown />
          </button>
          {filterOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setFilterOpen(false)} />
              <ul className="absolute right-0 top-full z-20 mt-1 max-h-60 w-36 overflow-y-auto rounded-lg border border-border-light bg-white py-1 shadow-lg">
                <li>
                  <button
                    onClick={() => {
                      setFilterCls(null);
                      setFilterOpen(false);
                    }}
                    className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-xs hover:bg-surface ${
                      filterCls === null ? "text-primary" : "text-gray-600"
                    }`}
                  >
                    全部 <span className="text-gray-400">{tracks.length}</span>
                  </button>
                </li>
                {clsCounts.map(({ cls, count }) => (
                  <li key={cls}>
                    <button
                      onClick={() => {
                        setFilterCls(cls);
                        setFilterOpen(false);
                      }}
                      className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-xs hover:bg-surface ${
                        filterCls === cls ? "text-primary" : "text-gray-600"
                      }`}
                    >
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colorOf(cls) }} />
                        {zh(cls)}
                      </span>
                      <span className="text-gray-400">{count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      {/* 列表 */}
      {visible.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center">
          <p className="text-xs text-gray-400">
            {tracks.length === 0 ? "暂无检测结果（需开启目标检测并解析完成）" : "该类别暂无目标"}
          </p>
        </div>
      ) : (
        <ul className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto p-2">
          {visible.map((t) => (
            <li
              key={t.track_id}
              onClick={() => onSeek(t.first_seen)}
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-border-light bg-surface px-2.5 py-2 transition-colors hover:border-primary/40"
              title="点击定位到出现时刻"
            >
              <TrackThumb videoId={video?.id ?? null} track={t} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-gray-800">
                    {zh(t.class_name)} #{t.display_seq ?? t.track_id}
                  </span>
                  {identityByTrack.get(t.track_id) && (
                    <span className="shrink-0 rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-600">
                      {identityByTrack.get(t.track_id)}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs tabular-nums text-gray-400">
                  {formatSec(t.first_seen)} - {formatSec(t.last_seen)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleWatch(t.track_id);
                  }}
                  title={watched.has(t.track_id) ? "取消关注" : "添加到关注列表"}
                  className={`flex h-7 w-7 items-center justify-center rounded-full border transition-colors ${
                    watched.has(t.track_id)
                      ? "border-primary bg-primary-soft text-primary"
                      : "border-border-light text-gray-400 hover:border-primary/50 hover:text-primary"
                  }`}
                >
                  <IconPlus />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    void exportThumb(t);
                  }}
                  title="导出该目标截图"
                  className="flex h-7 w-7 items-center justify-center rounded-full border border-border-light text-gray-400 transition-colors hover:border-primary/50 hover:text-primary"
                >
                  <IconDownload />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* 轨迹缩略图：优先后端截图，失败/无源时显示类别色块占位 */
function TrackThumb({ videoId, track }: { videoId: string | null; track: Track }) {
  const [failed, setFailed] = useState(false);
  const src = track.thumbnail_url ?? (videoId ? api.getTrackThumbnailUrl(videoId, track.track_id, track.display_seq ?? undefined) : null);

  if (!src || failed) {
    return (
      <div
        className="flex h-12 w-[72px] shrink-0 items-center justify-center rounded-md text-white"
        style={{ backgroundColor: colorOf(track.class_name) }}
      >
        <IconVideo className="h-5 w-5 opacity-80" />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt=""
      onError={() => setFailed(true)}
      className="h-12 w-[72px] shrink-0 rounded-md object-cover"
    />
  );
}
