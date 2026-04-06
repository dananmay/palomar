"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import dynamic from "next/dynamic";
import { ChevronLeft, ChevronRight, AlertTriangle, MessageSquare } from "lucide-react";
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
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [tabFlash, setTabFlash] = useState(false);
  const prevCountRef = useRef(anomalies.length);

  // Flash the left toggle tab when new anomalies arrive while sidebar is collapsed
  useEffect(() => {
    if (leftCollapsed && anomalies.length > prevCountRef.current) {
      setTabFlash(true);
      const timer = setTimeout(() => setTabFlash(false), 1000);
      return () => clearTimeout(timer);
    }
    prevCountRef.current = anomalies.length;
  }, [anomalies.length, leftCollapsed]);

  const handleCursorMove = useCallback(
    (lat: number, lng: number) => handleMouseCoords({ lat, lng }),
    [handleMouseCoords],
  );

  return (
    <div className="flex h-screen w-screen bg-[#0a0a0a]">
      {/* Left: Anomaly sidebar */}
      <div className={`transition-all duration-200 overflow-hidden ${leftCollapsed ? 'w-0' : 'w-80'}`}>
        <div className="w-80 h-full">
          <AnomalySidebar
            anomalies={anomalies}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDeselect={() => setSelectedId(null)}
            status={status}
          />
        </div>
      </div>

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

          {/* Floating collapse/expand toggles */}
          <button
            onClick={() => setLeftCollapsed(!leftCollapsed)}
            className={`absolute left-0 top-4 z-10 bg-[#141414] border border-[#2a2a2a] border-l-0 rounded-r-lg p-2.5 text-[#666] hover:text-[#e5e5e5] hover:bg-[#1a1a1a] transition-colors ${tabFlash ? 'animate-[tab-flash_1s_ease]' : ''}`}
            title={leftCollapsed ? "Show anomalies" : "Hide anomalies"}
          >
            {leftCollapsed ? <AlertTriangle size={20} /> : <ChevronLeft size={18} />}
          </button>
          <button
            onClick={() => setRightCollapsed(!rightCollapsed)}
            className="absolute right-0 top-4 z-10 bg-[#141414] border border-[#2a2a2a] border-r-0 rounded-l-lg p-2.5 text-[#666] hover:text-[#e5e5e5] hover:bg-[#1a1a1a] transition-colors"
            title={rightCollapsed ? "Show chat" : "Hide chat"}
          >
            {rightCollapsed ? <MessageSquare size={18} /> : <ChevronRight size={18} />}
          </button>
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
      <div className={`transition-all duration-200 overflow-hidden ${rightCollapsed ? 'w-0' : 'w-80'}`}>
        <div className="w-80 h-full border-l border-[#2a2a2a]">
          <ChatSidebar selectedAnomalyId={selectedId} />
        </div>
      </div>
    </div>
  );
}
