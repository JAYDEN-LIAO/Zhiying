/* ════════════════════════════════════════════════════════════
   RightPanel — two 340px columns in 5:2.5:2.5 layout
   v0.19: group-aware (passes groupVideos + detectionVideoId to DetectionPanel)
   ════════════════════════════════════════════════════════════ */

import { VideoInfoCard } from "./VideoInfoCard";
import { VideoSummaryCard } from "./VideoSummaryCard";
import { VideoSearchCard } from "./VideoSearchCard";
import { DetectionPanel } from "./DetectionPanel";
import type { VideoResponse, VideoListItem, DetectionData, FaceData, PlateData } from "../types";

interface Props {
  videoId: string | null;
  video: VideoResponse | null;
  detectionData: DetectionData | null;
  faceData: FaceData | null;
  plateData: PlateData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  onClassFilterChange: (cls: string | null) => void;
  onTrackSelect: (trackId: number, className: string, seekTo?: number) => void;
  onSeekTo: (start: number, end: number | null) => void;
  /* 搜索 track 结果点击：带 video_id（供 Dashboard 同步检测面板到结果视频）*/
  onSearchTrackResult: (videoId: string, trackId: number, className: string, start: number) => void;
  /* 搜索人脸结果点击：定位到检测栏"人脸"视图并展开身份（v0.30）*/
  onSearchFaceResult: (videoId: string, identityId: number, ts: number) => void;
  /* ── 人脸视图外部控制（v0.30: 由 Dashboard 提升，供搜索人脸结果定位） ── */
  faceViewOpen: boolean;
  expandedFaceId: number | null;
  onFaceViewChange: (v: boolean) => void;
  onExpandedFaceChange: (v: number | null) => void;
  /* ── v0.19 组感知 ── */
  groupVideos?: string[];
  videos?: VideoListItem[];
  detectionVideoId?: string | null;
  onDetectionVideoChange?: (videoId: string | null) => void;
  onGroupVideoSwitch?: (videoId: string) => void;
}

export function RightPanel({
  videoId,
  video,
  detectionData,
  faceData,
  plateData,
  selectedTrackId,
  classFilter,
  onClassFilterChange,
  onTrackSelect,
  onSeekTo,
  onSearchTrackResult,
  onSearchFaceResult,
  faceViewOpen,
  expandedFaceId,
  onFaceViewChange,
  onExpandedFaceChange,
  groupVideos,
  videos,
  detectionVideoId,
  onDetectionVideoChange,
  onGroupVideoSwitch,
}: Props) {
  return (
    <div className="right-area">
      {/* ──── Left Column: DetectionPanel (full height) ──── */}
      <div className="right-col">
        <DetectionPanel
          video={video}
          data={detectionData}
          selectedTrackId={selectedTrackId}
          classFilter={classFilter}
          onClassFilterChange={onClassFilterChange}
          onTrackSelect={onTrackSelect}
          faceViewOpen={faceViewOpen}
          expandedFaceId={expandedFaceId}
          onFaceViewChange={onFaceViewChange}
          onExpandedFaceChange={onExpandedFaceChange}
          onSeekTo={(s, e) => onSeekTo(s, e)}
          faceData={faceData}
          plateData={plateData}
          groupVideos={groupVideos}
          videos={videos ?? []}
          detectionVideoId={detectionVideoId}
          onDetectionVideoChange={onDetectionVideoChange}
        />
      </div>

      {/* ──── Right Column: Search(5) + Summary(2.5) + Info(2.5) ──── */}
      <div className="right-col-5-2-2">
        {/* VideoSearch: major-card, flex: 5 */}
        <VideoSearchCard
          video={video}
          onSeekTo={(start, end) => onSeekTo(start, end)}
          onTrackResult={(videoId, trackId, className, start) => {
            onSearchTrackResult(videoId, trackId, className, start);
          }}
          onFaceResult={(videoId, identityId, ts) => onSearchFaceResult(videoId, identityId, ts)}
          groupVideos={groupVideos}
          allVideos={videos}
          onGroupVideoSwitch={onGroupVideoSwitch}
        />

        {/* VideoSummary: minor-card, flex: 2.5 */}
        <VideoSummaryCard video={video} />

        {/* VideoInfo: minor-card, flex: 2.5 */}
        <VideoInfoCard videoId={videoId} video={video} />
      </div>
    </div>
  );
}
