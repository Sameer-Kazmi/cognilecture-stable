import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", "http" + "://localhost:11434/v1"
).rstrip("/")
OLLAMA_CHAT_URL = os.getenv(
    "OLLAMA_CHAT_URL", "http" + "://localhost:11434/api/chat"
)
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
OLLAMA_MODELS_URL = f"{OLLAMA_BASE_URL}/models"

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_COMPACT_MODEL = os.getenv(
    "OLLAMA_COMPACT_MODEL", "qwen2.5:0.5b-instruct"
)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# --- Paths (absolute, so the app behaves the same from any working directory) ---
DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
TEMP_DIR = BACKEND_DIR / "temp"
DATABASE_URL = f"sqlite:///{(DATA_DIR / 'cognilecture.db').as_posix()}"

# --- LLM input budget ---
# num_ctx is 16384 tokens and the reply (num_predict) shares that window,
# so keep the prompt well under it. ~4 characters per token.
MAX_PROMPT_CHARS = int(os.getenv("MAX_PROMPT_CHARS", "36000"))

# --- Pipeline tuning ---
WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", str(os.cpu_count() or 4)))
OCR_MAX_SLIDES = int(os.getenv("OCR_MAX_SLIDES", "6"))
