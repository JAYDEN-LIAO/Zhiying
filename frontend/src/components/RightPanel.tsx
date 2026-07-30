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
          onTrackResult={(trackId, className, start) => {
            onTrackSelect(trackId, className, start);
          }}
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
