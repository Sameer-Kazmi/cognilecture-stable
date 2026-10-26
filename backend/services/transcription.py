from faster_whisper import WhisperModel

# Use "base" by default for 4x faster CPU speed with high accuracy, or customize via .env
from config import WHISPER_MODEL, WHISPER_CPU_THREADS

MODEL_SIZE = WHISPER_MODEL

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        # Thread count comes from WHISPER_CPU_THREADS (defaults to the machine's core count)
        _whisper_model = WhisperModel(
            MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            cpu_threads=WHISPER_CPU_THREADS
        )
    return _whisper_model

def transcribe_audio(audio_path: str) -> str:
    model = get_whisper_model()
    # beam_size=1 uses greedy decoding, running ~3-4x faster than beam_size=5
    segments, info = model.transcribe(audio_path, beam_size=1)
    
    transcript = ""
    for segment in segments:
        transcript += f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}\n"

    return transcript
