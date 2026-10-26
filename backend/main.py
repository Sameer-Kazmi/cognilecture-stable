import sys
import io

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from starlette.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import requests
import os
import time

from database import engine, Base, get_db, SessionLocal
from models import models
from services.ingestion import download_video_and_extract_audio
from services.transcription import transcribe_audio
from services.llm import generate_notes, generate_diagrams, generate_quiz, strip_timestamps
from config import MAX_PROMPT_CHARS
from services.ocr import extract_slides_text, merge_slides_into_transcript
from services.charts import extract_and_plot_trends
from services.rag import RAGStore
from services.export import export_markdown_to_pdf

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Lecture Video Analyzer")

# Enable CORS for frontend requests (e.g. from Vite on port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    """Always HTTP 200 while the API is up; the body says whether Ollama and the models are ready."""
    from config import OLLAMA_MODELS_URL, OLLAMA_MODEL, OLLAMA_COMPACT_MODEL
    ollama_ok, missing = False, []
    try:
        ids = [m.get("id") for m in requests.get(OLLAMA_MODELS_URL, timeout=2).json().get("data", [])]
        ollama_ok = True
        missing = [m for m in {OLLAMA_MODEL, OLLAMA_COMPACT_MODEL} if m not in ids]
    except Exception:
        pass
    return {"status": "ok" if ollama_ok and not missing else "degraded",
            "ollama_reachable": ollama_ok, "missing_models": missing}

class AnalyzeRequest(BaseModel):
    url: str
    
class ChatRequest(BaseModel):
    lecture_id: int
    question: str
    history: List[dict] = []

def _quiz_source(transcript: str, notes_markdown: str) -> str:
    """Whole transcript when it fits the prompt budget; otherwise the notes (they cover the full lecture)."""
    plain = strip_timestamps(transcript or "")
    return plain if len(plain) <= MAX_PROMPT_CHARS or not notes_markdown else notes_markdown


def _set_stage(db, lecture, stage: str, status: str = "processing"):
    lecture.status, lecture.stage = status, stage
    db.commit()
    print(f"[{lecture.id}] {stage}", flush=True)


def process_video_task(lecture_id: int, url: str):
    db = SessionLocal()
    media_info = None
    start_time = time.time()
    try:
        lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()

        _set_stage(db, lecture, "Downloading video and extracting audio")
        media_info = download_video_and_extract_audio(url)
        lecture.title = media_info["title"]
        lecture.duration_sec = int(media_info["duration_sec"] or 0)
        db.commit()

        _set_stage(db, lecture, "Transcribing audio")
        transcript = transcribe_audio(media_info["audio_path"])

        _set_stage(db, lecture, "Reading slide text")
        slides = extract_slides_text(media_info["video_path"])
        lecture.transcript = merge_slides_into_transcript(transcript, slides)
        db.commit()

        _set_stage(db, lecture, "Writing study notes")
        notes_content = generate_notes(lecture.transcript)

        _set_stage(db, lecture, "Drawing diagram and chart")
        diagrams_content = generate_diagrams(notes_content)
        charts_content = extract_and_plot_trends(notes_content)
        final_markdown = notes_content
        if charts_content:
            final_markdown += "\n\n## Charts\n" + charts_content

        _set_stage(db, lecture, "Generating quiz")
        quiz_json = generate_quiz(_quiz_source(lecture.transcript, notes_content))

        db.add(models.Note(lecture_id=lecture.id, content_markdown=final_markdown, diagrams=diagrams_content))
        db.add(models.Quiz(lecture_id=lecture.id, questions=quiz_json))
        lecture.status, lecture.stage, lecture.error = "completed", "Done", None
        db.commit()
        print(f"[{lecture.id}] SUCCESS in {round(time.time() - start_time, 1)}s", flush=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        db.rollback()
        lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
        if lecture:
            lecture.status, lecture.error = "failed", f"{lecture.stage or 'Processing'} failed: {e}"
            db.commit()
    finally:
        if media_info:                      # always clean temp files, success or failure
            for key in ("video_path", "audio_path"):
                path = media_info.get(key)
                if path and os.path.exists(path):
                    os.remove(path)
        db.close()


@app.post("/analyze")
def analyze_video(request: AnalyzeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    lecture = models.Lecture(source_url=request.url, title=request.url, status="queued", stage="Waiting to start")
    db.add(lecture)
    db.commit()
    db.refresh(lecture)
    background_tasks.add_task(process_video_task, lecture.id, request.url)
    return {"message": "Video processing started in background.", "lecture_id": lecture.id}


def _lecture_summary(l: models.Lecture) -> dict:
    # Deliberately excludes the (large) transcript.
    return {"id": l.id, "source_url": l.source_url, "title": l.title, "duration_sec": l.duration_sec,
            "status": l.status or "completed", "stage": l.stage, "error": l.error,
            "created_at": l.created_at}


@app.get("/lectures")
def get_lectures(db: Session = Depends(get_db)):
    rows = db.query(models.Lecture).order_by(models.Lecture.created_at.desc(), models.Lecture.id.desc()).all()
    return [_lecture_summary(l) for l in rows]


@app.get("/lectures/{lecture_id}")
def get_lecture(lecture_id: int, db: Session = Depends(get_db)):
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return _lecture_summary(lecture)


@app.get("/lectures/{lecture_id}/notes")
def get_notes(lecture_id: int, db: Session = Depends(get_db)):
    note = db.query(models.Note).filter(models.Note.lecture_id == lecture_id).first()
    if not note:
        lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
        if lecture and lecture.status in ("queued", "processing"):
            raise HTTPException(status_code=409, detail=f"Still processing: {lecture.stage}")
        raise HTTPException(status_code=404, detail="Notes not found")
    return note


@app.get("/lectures/{lecture_id}/quiz")
def get_quiz(lecture_id: int, db: Session = Depends(get_db)):
    quiz = db.query(models.Quiz).filter(models.Quiz.lecture_id == lecture_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz

# Simple cache for RAG stores per lecture
rag_stores = {}

@app.post("/chat")
def chat_with_lecture(request: ChatRequest, db: Session = Depends(get_db)):
    lecture = db.query(models.Lecture).filter(models.Lecture.id == request.lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
        
    if request.lecture_id not in rag_stores:
        store = RAGStore()
        store.add_document(lecture.transcript)
        rag_stores[request.lecture_id] = store
        
    store = rag_stores[request.lecture_id]
    answer = store.query(request.question, history=request.history)
    
    # Save chat log
    chat_log_user = models.ChatLog(lecture_id=lecture.id, role="user", message=request.question)
    chat_log_assistant = models.ChatLog(lecture_id=lecture.id, role="assistant", message=answer)
    db.add(chat_log_user)
    db.add(chat_log_assistant)
    db.commit()
    
    return {"answer": answer}

@app.get("/lectures/{lecture_id}/export")
def export_notes_pdf(lecture_id: int, db: Session = Depends(get_db)):
    note = db.query(models.Note).filter(models.Note.lecture_id == lecture_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Notes not found")
    try:
        pdf_path = export_markdown_to_pdf(note.content_markdown)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return FileResponse(
        pdf_path, media_type="application/pdf", filename=f"lecture_{lecture_id}_notes.pdf",
        background=BackgroundTask(os.remove, pdf_path),   # delete the temp PDF after it is sent
    )

from services.thermal_agent import thermal_agent

class SpikeSimulationRequest(BaseModel):
    simulate: bool

class PhysicalStressRequest(BaseModel):
    enabled: bool

@app.get("/system/thermal")
def get_system_thermal():
    """
    Returns ESTIMATED thermal telemetry (not a hardware reading) and the current model-tier decision.
    """
    return thermal_agent.select_model(learn=False)   # read-only: polling must not train the agent

@app.post("/system/thermal/simulate-spike")
def toggle_thermal_spike(request: SpikeSimulationRequest):
    """
    Demonstration trigger: simulates a thermal spike (fixed ~82.5 C) to demonstrate the model fallback.
    """
    thermal_agent.sensor.toggle_simulated_spike(request.simulate)
    return {
        "message": f"Thermal spike simulation {'enabled (82.5 C)' if request.simulate else 'disabled (normal sensor readings)'}",
        "simulated": request.simulate
    }

@app.post("/system/thermal/physical-stress")
def toggle_physical_stress(request: PhysicalStressRequest):
    """
    Demo trigger: runs a real multi-core matrix workload (genuine CPU load). The displayed
    temperature remains an estimate/ramped value, not a sensor reading.
    """
    active = thermal_agent.sensor.toggle_physical_stress(request.enabled)
    return {
        "message": f"CPU stress workload {'started (100% Core Load)' if active else 'stopped'}",
        "physical_stress_active": active
    }

from typing import Literal

class RegenerateQuizRequest(BaseModel):
    difficulty: Literal["easy", "medium", "hard"]

@app.post("/lectures/{lecture_id}/quiz/regenerate")
def regenerate_lecture_quiz(
    lecture_id: int,
    request: RegenerateQuizRequest,
    db: Session = Depends(get_db),
):
    """Regenerate the quiz at the requested difficulty."""
    lecture = (
        db.query(models.Lecture)
        .filter(models.Lecture.id == lecture_id)
        .first()
    )
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    difficulty = request.difficulty
    note = db.query(models.Note).filter(models.Note.lecture_id == lecture_id).first()
    quiz_json = generate_quiz(
        _quiz_source(lecture.transcript, note.content_markdown if note else ""),
        difficulty=difficulty,
    )

    existing_quiz = (
        db.query(models.Quiz)
        .filter(models.Quiz.lecture_id == lecture_id)
        .first()
    )

    if existing_quiz:
        existing_quiz.questions = quiz_json
    else:
        existing_quiz = models.Quiz(
            lecture_id=lecture_id,
            questions=quiz_json,
        )
        db.add(existing_quiz)

    db.commit()
    db.refresh(existing_quiz)

    return {
        "difficulty": difficulty,
        "quiz": existing_quiz,
    }





