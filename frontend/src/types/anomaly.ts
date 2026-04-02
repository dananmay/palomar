export interface Anomaly {
  anomaly_id: string;
  domain: "aircraft" | "maritime" | "seismic" | "gdelt";
  rule: string;
  severity: number; // 1=LOW, 2=MEDIUM, 3=HIGH, 4=CRITICAL
  severity_label: string;
  title: string;
  description: string;
  lat: number | null;
  lng: number | null;
  entity_id: string;
  metadata: Record<string, unknown>;
  detected_at: number; // Unix timestamp
  updated_at: number;
  expires_at: number;
}

export type BackendStatus = "connecting" | "connected" | "disconnected";
