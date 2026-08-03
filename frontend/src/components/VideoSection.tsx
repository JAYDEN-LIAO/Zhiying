/* ════════════════════════════════════════════════════════════
   VideoSection — middle column orchestrator
   Composes VideoPlayer + DetectionTimeline + PipelineBar
   ════════════════════════════════════════════════════════════ */

import { RefObject } from "react";
import { VideoPlayer } from "./VideoPlayer";
import { DetectionTimeline } from "./DetectionTimeline";
import { PipelineBar } from "./PipelineBar";
import type { VideoResponse, DetectionData, FaceData, ProxyStatus, PipelineStage } from "../types";

interface Props {
  videoId: string | null;
  video: VideoResponse | null;
  streamReady: boolean;
  hevcOk: boolean;
  isUploading: boolean;
  detectionEnabled: boolean;
  hasDetection: boolean;
  detectionData: DetectionData | null;
  faceData: FaceData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  proxyStatus: ProxyStatus | null;
  pipelineStages: PipelineStage[];
  videoRef: RefObject<HTMLVideoElement | null>;
  onTrackSelect: (trackId: number, className: string, seekTo?: number) => void;
}

export function VideoSection({
  videoId,
  video,
  streamReady,
  hevcOk,
  isUploading,
  detectionEnabled,
  hasDetection,
  detectionData,
  faceData,
  selectedTrackId,
  classFilter,
  proxyStatus,
  pipelineStages,
  videoRef,
  onTrackSelect,
}: Props) {
  return (
    <div className="video-section">
      <VideoPlayer
        videoId={videoId}
        video={video}
        streamReady={streamReady}
        hevcOk={hevcOk}
        isUploading={isUploading}
        detectionEnabled={detectionEnabled}
        hasDetection={hasDetection && detectionEnabled && !!detectionData?.has_detection}
        selectedTrackId={selectedTrackId}
        proxyStatus={proxyStatus}
        videoRef={videoRef}
        onTrackSelect={(tid, cls) => onTrackSelect(tid, cls)}
      />

      {/* Detection Timeline */}
      <DetectionTimeline
        videoId={videoId ?? ""}
        videoRef={videoRef}
        selectedTrackId={selectedTrackId}
        classFilter={classFilter}
        onTrackSelect={onTrackSelect}
        data={detectionData}
        faceData={faceData}
        streamReady={streamReady}
      />

      {/* Pipeline Bar */}
      <div className="pipeline-wrap">
        <PipelineBar
          progress={video?.progress ?? 0}
          statusDetail={video?.status_detail}
          stages={pipelineStages}
          subtitle={video?.status === "pending" ? "等待参数配置..." : null}
        />
      </div>
    </div>
  );
}
