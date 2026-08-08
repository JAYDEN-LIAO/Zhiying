import { useEffect, useRef } from "react";
import { api } from "../services/api";
import type { VideoResponse } from "../types";

interface UseVideoPollingOptions {
  videoId: string | null;
  onUpdate: (video: VideoResponse) => void;
  intervalMs?: number;
}

/**
 * Polls video detail every `intervalMs` while status is "processing" or "pending".
 * Pauses when tab is hidden (visibilitychange), resumes when visible.
 */
export function useVideoPolling({ videoId, onUpdate, intervalMs = 3000 }: UseVideoPollingOptions) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    if (!videoId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      try {
        const data = await api.getVideo(videoId);
        if (cancelled) return;
        onUpdateRef.current(data);
        if (data.status !== "processing" && data.status !== "pending") {
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
        }
      } catch {
        // retry on next interval
      }
    };

    poll();
    timer = setInterval(poll, intervalMs);

    // Visibility-aware: pause polling when tab hidden
    const onVisibility = () => {
      if (document.hidden && timer) {
        clearInterval(timer);
        timer = null;
      } else if (!document.hidden && !timer && !cancelled) {
        poll();
        timer = setInterval(poll, intervalMs);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [videoId, intervalMs]);
}
