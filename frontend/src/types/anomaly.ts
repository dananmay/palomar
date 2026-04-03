export interface Anomaly {
  anomaly_id: string;
  domain: "aircraft" | "maritime" | "seismic" | "gdelt" | "fires" | "infrastructure" | "cross_domain";
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
  // Tier 2 triage fields (null before triage runs or if no model configured)
  ai_context: string | null;
  ai_highlighted: boolean;
  ai_highlight_reason: string | null;
  ai_model: string | null;
  ai_analyzed_at: number | null;
}

export type BackendStatus = "connecting" | "connected" | "disconnected";
