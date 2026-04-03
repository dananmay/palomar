"use client";

import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import AnomalySidebar from "@/components/AnomalySidebar";
import ChatSidebar from "@/components/ChatSidebar";
import ErrorBoundary from "@/components/ErrorBoundary";
import { useAnomalyPolling } from "@/hooks/useAnomalyPolling";
import { useReverseGeocode } from "@/hooks/useReverseGeocode";

const AnomalyMap = dynamic(() => import("@/components/AnomalyMap"), { ssr: false });

export default function Home() {
  const { anomalies, status } = useAnomalyPolling();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { mouseCoords, locationLabel, handleMouseCoords } = useReverseGeocode();

  const handleCursorMove = useCallback(
    (lat: number, lng: number) => handleMouseCoords({ lat, lng }),
    [handleMouseCoords],
  );

  return (
    <div className="flex h-screen w-screen bg-[#0a0a0a]">
      {/* Left: Anomaly sidebar */}
      <AnomalySidebar
        anomalies={anomalies}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onDeselect={() => setSelectedId(null)}
        status={status}
      />

      {/* Center: Map + coordinate bar */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 relative">
          <ErrorBoundary>
            <AnomalyMap
              anomalies={anomalies}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onCursorMove={handleCursorMove}
            />
          </ErrorBoundary>
        </div>

        {/* Coordinate bar */}
        {mouseCoords && (
          <div className="h-8 px-4 flex items-center border-t border-[#2a2a2a] bg-[#0a0a0a] text-xs text-[#666] font-mono gap-4">
            <span>
              {mouseCoords.lat.toFixed(4)}, {mouseCoords.lng.toFixed(4)}
            </span>
            {locationLabel && (
              <>
                <span className="text-[#333]">·</span>
                <span className="text-[#555] font-sans truncate">{locationLabel}</span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Right: Chat sidebar */}
      <ChatSidebar selectedAnomalyId={selectedId} />
    </div>
  );
}
