"""Download the models the pipeline needs, once, so the first lecture doesn't stall.
Run from the backend folder:  python scripts/preload_models.py
(Ollama models are separate: `ollama pull <model>`.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import WHISPER_MODEL

print(f"[1/3] faster-whisper '{WHISPER_MODEL}' ...")
from faster_whisper import WhisperModel
WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

print("[2/3] EasyOCR English model ...")
import easyocr
easyocr.Reader(["en"])

print("[3/3] Sentence-Transformers all-MiniLM-L6-v2 ...")
from sentence_transformers import SentenceTransformer
SentenceTransformer("all-MiniLM-L6-v2")

print("Done. Models are cached locally.")
