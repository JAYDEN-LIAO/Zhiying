import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { ProxyStatus } from "../types";

/**
 * Polls proxy transcode status every 3s while the video needs a proxy.
 * Stops when status is "ready" or "failed".
 * When ready, calls `onReady()` so the caller can reload the video element.
 */
export function useProxyStatus(
  videoId: string | null,
  needsProxy: boolean,
  onReady?: () => void,
): ProxyStatus | null {
  const [status, setStatus] = useState<ProxyStatus | null>(null);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    if (!videoId || !needsProxy) {
      setStatus(null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      try {
        const s = await api.getProxyStatus(videoId);
        if (cancelled) return;
        setStatus(s);
        if (s.status === "ready" || s.status === "failed") {
          if (timer) clearInterval(timer);
          if (s.status === "ready") {
            onReadyRef.current?.();
          }
        }
      } catch {
        // ignore
      }
    };

    poll();
    timer = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [videoId, needsProxy]);

  return status;
}
