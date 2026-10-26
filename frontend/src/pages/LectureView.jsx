import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import mermaid from "mermaid";
import PageHeader from "../components/layout/PageHeader";
import Card from "../components/ui/Card";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import ChatWidget from "../components/ChatWidget";
import MarkdownRenderer from "../components/MarkdownRenderer";
import Spinner from "../components/ui/Spinner";
import EmptyState from "../components/ui/EmptyState";
import api, { downloadLecturePdf, describeError } from "../api/client";
import { useToast } from "../hooks/useToast";

mermaid.initialize({ startOnLoad: false, theme: "default" });

export default function LectureView() {
  const { id } = useParams();
  const [note, setNote] = useState(null);
  const [lecture, setLecture] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [diagramCollapsed, setDiagramCollapsed] = useState(false);
  const [diagramError, setDiagramError] = useState(false);
  const { showToast } = useToast();
  const mermaidRef = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [noteRes, lecturesRes] = await Promise.all([
        api.get(`/lectures/${id}/notes`),
        api.get("/lectures"),
      ]);
      setNote(noteRes.data);
      const currentLecture = (lecturesRes.data || []).find((l) => String(l.id) === String(id));
      setLecture(currentLecture);
    } catch (err) {
      setError(
        err.response?.status === 409
          ? `This lecture is still being processed (${err.response.data?.detail || "please wait"}). Check the Dashboard for progress.`
          : "Notes not found. The lecture may have failed to process; check its status on the Dashboard."
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    let isMounted = true;
    setDiagramError(false);
    if (note?.diagrams && mermaidRef.current && !diagramCollapsed) {
      const uniqueId = `mermaid-chart-${id}-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      // The backend already sanitizes the diagram; render it as-is.
      mermaid
        .render(uniqueId, note.diagrams)
        .then(({ svg }) => {
          if (isMounted && mermaidRef.current) mermaidRef.current.innerHTML = svg;
        })
        .catch((err) => {
          console.warn("Mermaid render error:", err);
          document.getElementById("d" + uniqueId)?.remove();
          if (isMounted) setDiagramError(true); // say so honestly instead of showing a fake diagram
        });
    }
    return () => {
      isMounted = false;
    };
  }, [note, id, diagramCollapsed]);

  const handleExportPDF = async () => {
    try {
      await downloadLecturePdf(id);
    } catch (err) {
      showToast(await describeError(err, "PDF export failed."), "error");
    }
  };

  const formatDuration = (seconds) => {
    if (!seconds && seconds !== 0) return null;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs.toString().padStart(2, "0")}s`;
  };

  if (loading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center text-center">
        <Spinner size="lg" className="mb-4" />
        <h3 className="text-base font-semibold text-slate-800">Loading lecture notes & diagrams...</h3>
        <p className="text-xs text-slate-400 mt-1">Fetching generated markdown and transcript</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-12">
        <EmptyState
          title="Lecture Notes Not Found"
          description={error}
          actionText="Back to Dashboard"
          onAction={() => window.location.href = "/"}
        />
      </div>
    );
  }

  return (
    <div>
      {/* Page Header with Breadcrumbs & Actions */}
      <PageHeader
        breadcrumbs={[
          { to: "/", label: "Dashboard" },
          { label: lecture?.title || `Lecture #${id}` },
        ]}
        title={lecture?.title || `Lecture #${id} Summary`}
        subtitle={
          lecture?.duration_sec
            ? `Duration: ${formatDuration(lecture.duration_sec)} • Generated via Whisper ASR & Ollama`
            : "Generated via Whisper ASR & Ollama"
        }
        badge={
          <Badge variant="brand" size="sm">
            Lecture #{id}
          </Badge>
        }
        actions={
          <>
            <Link to={`/lectures/${id}/quiz`}>
              <Button variant="success" size="sm">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                Take Practice Quiz
              </Button>
            </Link>

            <Button variant="secondary" size="sm" onClick={handleExportPDF}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export PDF
            </Button>
          </>
        }
      />

      {/* Main Grid: Content (Left) + AI Chat Widget (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 sm:gap-8 items-start">
        {/* Left Column: Flowchart + Study Notes */}
        <div className="lg:col-span-2 space-y-6">
          {/* Generated Process Flowchart Diagram */}
          {note?.diagrams && (
            <Card variant="default" padding="md" className="border-indigo-100 bg-white">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <span className="text-base">📊</span>
                  <h3 className="font-bold text-slate-900 text-sm tracking-tight">
                    Generated Process & Concept Flowchart
                  </h3>
                  <Badge variant="purple" size="xs">
                    Mermaid.js
                  </Badge>
                </div>

                <button
                  onClick={() => setDiagramCollapsed((prev) => !prev)}
                  className="text-xs text-slate-500 hover:text-slate-800 font-medium px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
                >
                  {diagramCollapsed ? "Show Diagram" : "Hide Diagram"}
                </button>
              </div>

              {!diagramCollapsed && (
                <div
                  ref={mermaidRef}
                  className="overflow-x-auto flex justify-center py-6 px-2 bg-slate-50/70 rounded-xl border border-slate-200/60 transition-all min-h-[140px]"
                />
              )}
              {!diagramCollapsed && diagramError && (
                <div className="mt-3 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3">
                  The generated diagram could not be rendered. Raw definition:
                  <pre className="mt-2 overflow-x-auto text-[11px] text-slate-700">{note.diagrams}</pre>
                </div>
              )}
            </Card>
          )}

          {/* Structured Study Notes */}
          <Card variant="raised" padding="lg" className="bg-white">
            <div className="pb-4 mb-6 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-extrabold text-slate-900 tracking-tight">
                  Comprehensive Study Notes & Summary
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Extracted from audio transcript and slide vision OCR
                </p>
              </div>
            </div>

            <MarkdownRenderer content={note?.content_markdown} />
          </Card>
        </div>

        {/* Right Column: Sticky AI Lecture Chatbot */}
        <div className="lg:col-span-1 lg:sticky lg:top-24">
          <ChatWidget lectureId={id} />
        </div>
      </div>
    </div>
  );
}
