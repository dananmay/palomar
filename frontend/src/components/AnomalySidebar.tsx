"use client";

import { useMemo } from "react";
import { ArrowLeft } from "lucide-react";
import type { Anomaly } from "@/types/anomaly";

interface Props {
  anomalies: Anomaly[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDeselect: () => void;
  status: "connecting" | "connected" | "disconnected";
}

const SEVERITY_COLORS: Record<number, string> = {
  4: "#ef4444", // CRITICAL — red
  3: "#f97316", // HIGH — orange
  2: "#eab308", // MEDIUM — yellow
  1: "#64748b", // LOW — slate
};

const DOMAIN_LABELS: Record<string, string> = {
  aircraft: "Aircraft",
  maritime: "Maritime",
  seismic: "Seismic",
  gdelt: "GDELT",
};

function timeAgo(ts: number): string {
  const seconds = Math.floor(Date.now() / 1000 - ts);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export default function AnomalySidebar({ anomalies, selectedId, onSelect, onDeselect, status }: Props) {
  const selected = useMemo(
    () => anomalies.find((a) => a.anomaly_id === selectedId) ?? null,
    [anomalies, selectedId],
  );

  // Auto-deselect if selected anomaly expired (no longer in list)
  if (selectedId && !selected) {
    // Use setTimeout to avoid state update during render
    setTimeout(() => onDeselect(), 0);
  }

  const grouped = useMemo(() => {
    const groups: Record<number, Anomaly[]> = { 4: [], 3: [], 2: [], 1: [] };
    for (const a of anomalies) {
      (groups[a.severity] ??= []).push(a);
    }
    return groups;
  }, [anomalies]);

  return (
    <aside className="w-80 h-full flex flex-col border-r border-[#2a2a2a] bg-[#0a0a0a]">
      {/* Header */}
      <div className="px-5 py-4 border-b border-[#2a2a2a]">
        <h1 className="text-base font-semibold text-[#e5e5e5] tracking-tight">Palomar</h1>
        <div className="flex items-center gap-2 mt-1">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              backgroundColor:
                status === "connected" ? "#22c55e" : status === "connecting" ? "#eab308" : "#ef4444",
            }}
          />
          <span className="text-xs text-[#666]">
            {status === "connected"
              ? `${anomalies.length} active anomal${anomalies.length === 1 ? "y" : "ies"}`
              : status === "connecting"
                ? "Connecting..."
                : "Disconnected"}
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {selected ? (
          <DetailView anomaly={selected} onBack={onDeselect} />
        ) : anomalies.length === 0 ? (
          <EmptyState status={status} />
        ) : (
          <ListView groups={grouped} onSelect={onSelect} />
        )}
      </div>
    </aside>
  );
}

/* ── List View ── */

function ListView({
  groups,
  onSelect,
}: {
  groups: Record<number, Anomaly[]>;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="py-2">
      {[4, 3, 2, 1].map((sev) => {
        const items = groups[sev];
        if (!items || items.length === 0) return null;
        return (
          <div key={sev} className="mb-1">
            <div className="px-5 py-1.5 text-[10px] font-medium uppercase tracking-wider text-[#666]">
              {items[0].severity_label} ({items.length})
            </div>
            {items.map((a) => (
              <button
                key={a.anomaly_id}
                onClick={() => onSelect(a.anomaly_id)}
                className="w-full text-left px-5 py-3 hover:bg-[#1a1a1a] transition-colors border-b border-[#1a1a1a]"
              >
                <div className="flex items-start gap-2.5">
                  <span
                    className="mt-1 w-2 h-2 rounded-full flex-shrink-0"
                    style={{ backgroundColor: SEVERITY_COLORS[a.severity] }}
                  />
                  <div className="min-w-0">
                    <div className="text-sm text-[#e5e5e5] leading-snug line-clamp-2">
                      {a.title}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-[#666] bg-[#1a1a1a] px-1.5 py-0.5 rounded">
                        {DOMAIN_LABELS[a.domain] ?? a.domain}
                      </span>
                      <span className="text-[10px] text-[#555]">{timeAgo(a.detected_at)}</span>
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* ── Detail View ── */

function DetailView({ anomaly, onBack }: { anomaly: Anomaly; onBack: () => void }) {
  const color = SEVERITY_COLORS[anomaly.severity];

  return (
    <div className="p-5">
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-[#666] hover:text-[#a3a3a3] transition-colors mb-4"
      >
        <ArrowLeft size={14} />
        Back
      </button>

      {/* Severity + Domain */}
      <div className="flex items-center gap-2 mb-2">
        <span
          className="w-2.5 h-2.5 rounded-full"
          style={{ backgroundColor: color }}
        />
        <span className="text-xs font-medium uppercase tracking-wide" style={{ color }}>
          {anomaly.severity_label}
        </span>
        <span className="text-[10px] text-[#666] bg-[#1a1a1a] px-1.5 py-0.5 rounded">
          {DOMAIN_LABELS[anomaly.domain] ?? anomaly.domain}
        </span>
      </div>

      {/* Title */}
      <h2 className="text-base font-medium text-[#e5e5e5] leading-snug mb-3">
        {anomaly.title}
      </h2>

      {/* Description */}
      <p className="text-sm text-[#a3a3a3] leading-relaxed mb-4">
        {anomaly.description}
      </p>

      {/* Coordinates */}
      {anomaly.lat != null && anomaly.lng != null && (
        <div className="text-xs text-[#666] mb-4 font-mono">
          {anomaly.lat.toFixed(4)}, {anomaly.lng.toFixed(4)}
        </div>
      )}

      {/* Timestamps */}
      <div className="text-xs text-[#555] space-y-1 mb-4">
        <div>Detected {timeAgo(anomaly.detected_at)}</div>
        {anomaly.updated_at !== anomaly.detected_at && (
          <div>Updated {timeAgo(anomaly.updated_at)}</div>
        )}
      </div>

      {/* Metadata */}
      {Object.keys(anomaly.metadata).length > 0 && (
        <div className="border-t border-[#1a1a1a] pt-3">
          <div className="text-[10px] font-medium uppercase tracking-wider text-[#666] mb-2">
            Details
          </div>
          <div className="space-y-1.5">
            {Object.entries(anomaly.metadata).map(([key, value]) => {
              // Skip internal/complex fields
              if (key.startsWith("_") || typeof value === "object") return null;
              return (
                <div key={key} className="flex justify-between text-xs">
                  <span className="text-[#666]">{key.replace(/_/g, " ")}</span>
                  <span className="text-[#a3a3a3] font-mono text-right max-w-[60%] truncate">
                    {String(value)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Rule info */}
      <div className="mt-4 text-[10px] text-[#444] font-mono">
        {anomaly.domain}/{anomaly.rule} · {anomaly.entity_id}
      </div>
    </div>
  );
}

/* ── Empty State ── */

function EmptyState({ status }: { status: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-8 text-center">
      <div className="w-8 h-8 rounded-full border-2 border-[#2a2a2a] border-t-[#666] animate-spin mb-4" />
      <div className="text-sm text-[#666]">
        {status === "connecting" ? "Connecting to backend..." : "Monitoring..."}
      </div>
      <div className="text-xs text-[#444] mt-1">
        Anomalies will appear here when detected.
      </div>
    </div>
  );
}
