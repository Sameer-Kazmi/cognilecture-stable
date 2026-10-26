import Badge from "../components/ui/Badge";
import React, { useState, useEffect, useCallback } from "react";
import PageHeader from "../components/layout/PageHeader";
import SectionHeader from "../components/layout/SectionHeader";
import VideoSubmitForm from "../components/lectures/VideoSubmitForm";
import LectureList from "../components/lectures/LectureList";
import ThermalGovernor from "../components/telemetry/ThermalGovernor";
import { useTelemetry } from "../hooks/useTelemetry";
import api from "../api/client";

export default function Dashboard() {
  const [lectures, setLectures] = useState([]);
  const [lecturesLoading, setLecturesLoading] = useState(true);
  const [telemetryCollapsed, setTelemetryCollapsed] = useState(false);

    // Telemetry hook for the thermal governor
  const { thermal, refresh: refreshTelemetry } = useTelemetry(1500);

  const fetchLectures = useCallback(async () => {
    try {
      const res = await api.get("/lectures");
      setLectures(res.data || []);
    } catch (err) {
      console.error("Failed to fetch lectures:", err);
    } finally {
      setLecturesLoading(false);
    }
  }, []);

  const hasActive = lectures.some((l) => l.status === "queued" || l.status === "processing");

  useEffect(() => {
    fetchLectures();
    // Poll quickly only while something is being processed
    const timer = setInterval(fetchLectures, hasActive ? 3000 : 20000);
    return () => clearInterval(timer);
  }, [fetchLectures, hasActive]);

  const activeGovernorsCount = [
    thermal?.telemetry?.simulated || thermal?.telemetry?.physical_stress_active,
  ].filter(Boolean).length;

  return (
    <div>
      {/* Top Page Header */}
      <PageHeader
        title="Dashboard"
        subtitle="Submit lecture recordings for on-device transcription, structured notes, visual diagrams, and practice quizzes."
        badge={
          <Badge variant="brand" size="sm" dot pulse>
            Local Engine Active
          </Badge>
        }
      />

      {/* 1. Core Feature: Lecture Ingestion Hero */}
      <VideoSubmitForm onSubmitted={fetchLectures} />

      {/* 2. Processed Lectures Section */}
      <LectureList
        lectures={lectures}
        loading={lecturesLoading}
        onRefresh={fetchLectures}
      />

      {/* 3. Edge Hardware Governors & Telemetry (Collapsible Section) */}
      <div className="pt-6 border-t border-slate-200/80">
        <SectionHeader
          title="Thermal-Aware Model Selection"
                    subtitle="Estimated thermal state and thermal-aware model selection."
          badge={
            activeGovernorsCount > 0 ? (
              <Badge variant="warning" size="xs" dot pulse>
                {activeGovernorsCount} Simulation Active
              </Badge>
            ) : (
              <Badge variant="success" size="xs">
                All Systems Normal
              </Badge>
            )
          }
          collapsible
          isCollapsed={telemetryCollapsed}
          onToggle={() => setTelemetryCollapsed((prev) => !prev)}
          className="mb-4 cursor-pointer select-none p-2 -mx-2 rounded-xl hover:bg-slate-100/60 transition-colors"
        />

        {!telemetryCollapsed && (
          <div className="grid grid-cols-1 gap-5 animate-in fade-in duration-200">
            <ThermalGovernor thermal={thermal} onRefresh={refreshTelemetry} />
          </div>
        )}
      </div>
    </div>
  );
}
