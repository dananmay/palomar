"use client";

import { useRef, useEffect, useMemo, useCallback } from "react";
import Map, { Source, Layer, NavigationControl, ScaleControl } from "react-map-gl/maplibre";
import type { MapRef, MapLayerMouseEvent } from "react-map-gl/maplibre";
import type { Anomaly } from "@/types/anomaly";
import "maplibre-gl/dist/maplibre-gl.css";

interface Props {
  anomalies: Anomaly[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCursorMove: (lat: number, lng: number) => void;
}

const SEVERITY_COLORS: Record<number, string> = {
  4: "#ef4444",
  3: "#f97316",
  2: "#eab308",
  1: "#64748b",
};

const ANOMALY_LAYER_ID = "anomaly-circles";

export default function AnomalyMap({ anomalies, selectedId, onSelect, onCursorMove }: Props) {
  const mapRef = useRef<MapRef>(null);

  // Convert anomalies to GeoJSON — only include those with coordinates
  const geojson = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: anomalies
      .filter((a) => a.lat != null && a.lng != null)
      .map((a) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [a.lng!, a.lat!], // GeoJSON: [lng, lat]
        },
        properties: {
          anomaly_id: a.anomaly_id,
          severity: a.severity,
          title: a.title,
        },
      })),
  }), [anomalies]);

  // Fly to selected anomaly
  useEffect(() => {
    if (!selectedId || !mapRef.current) return;
    const anomaly = anomalies.find((a) => a.anomaly_id === selectedId);
    if (anomaly?.lat != null && anomaly?.lng != null) {
      mapRef.current.flyTo({
        center: [anomaly.lng, anomaly.lat],
        zoom: 6,
        duration: 1500,
      });
    }
  }, [selectedId, anomalies]);

  const handleClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0];
      if (feature?.properties?.anomaly_id) {
        onSelect(feature.properties.anomaly_id);
      }
    },
    [onSelect],
  );

  const handleMouseMove = useCallback(
    (e: MapLayerMouseEvent) => {
      onCursorMove(e.lngLat.lat, e.lngLat.lng);

      // Pointer cursor on anomaly markers
      const map = mapRef.current?.getMap();
      if (map && map.getLayer(ANOMALY_LAYER_ID)) {
        const features = map.queryRenderedFeatures(e.point, { layers: [ANOMALY_LAYER_ID] });
        map.getCanvas().style.cursor = features.length > 0 ? "pointer" : "";
      }
    },
    [onCursorMove],
  );

  return (
    <Map
      ref={mapRef}
      initialViewState={{
        longitude: 20,
        latitude: 25,
        zoom: 2.2,
      }}
      style={{ width: "100%", height: "100%" }}
      mapStyle="/map-style.json"
      reuseMaps
      interactiveLayerIds={[ANOMALY_LAYER_ID]}
      onClick={handleClick}
      onMouseMove={handleMouseMove}
    >
      <NavigationControl position="bottom-right" showCompass={false} style={{ marginBottom: "30px" }} />
      <ScaleControl position="bottom-right" />

      <Source id="anomalies" type="geojson" data={geojson}>
        {/* Outer glow for selected anomaly */}
        <Layer
          id="anomaly-selected-glow"
          type="circle"
          filter={selectedId ? ["==", ["get", "anomaly_id"], selectedId] : ["==", ["get", "anomaly_id"], ""]}
          paint={{
            "circle-radius": 18,
            "circle-color": "transparent",
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-opacity": 0.5,
          }}
        />
        {/* Main circles */}
        <Layer
          id={ANOMALY_LAYER_ID}
          type="circle"
          paint={{
            "circle-radius": [
              "match", ["get", "severity"],
              4, 8,
              3, 7,
              2, 6,
              5
            ],
            "circle-color": [
              "match", ["get", "severity"],
              4, SEVERITY_COLORS[4],
              3, SEVERITY_COLORS[3],
              2, SEVERITY_COLORS[2],
              SEVERITY_COLORS[1],
            ],
            "circle-opacity": 0.85,
            "circle-stroke-width": 1,
            "circle-stroke-color": "#000000",
            "circle-stroke-opacity": 0.5,
          }}
        />
      </Source>
    </Map>
  );
}
