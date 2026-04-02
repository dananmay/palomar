import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { Anomaly, BackendStatus } from "@/types/anomaly";

const STARTUP_INTERVAL = 3000;
const STEADY_INTERVAL = 15000;

export function useAnomalyPolling() {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [status, setStatus] = useState<BackendStatus>("connecting");
  const hasData = useRef(false);

  useEffect(() => {
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/anomalies`);
        if (res.ok) {
          const json = await res.json();
          setAnomalies(json.anomalies ?? []);
          setStatus("connected");
          hasData.current = true;
        }
      } catch {
        setStatus("disconnected");
      }
      timerId = setTimeout(poll, hasData.current ? STEADY_INTERVAL : STARTUP_INTERVAL);
    };

    poll();
    return () => {
      if (timerId) clearTimeout(timerId);
    };
  }, []);

  return { anomalies, status };
}
