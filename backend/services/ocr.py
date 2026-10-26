import re
from difflib import SequenceMatcher

from config import OCR_MAX_SLIDES

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        import easyocr  # imported lazily: keeps server start-up fast
        _reader = easyocr.Reader(["en"])
    return _reader


def _select_evenly(items: list, n: int) -> list:
    """Pick at most n items spread across the whole list (first and last included)."""
    if len(items) <= n:
        return items
    if n == 1:
        return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def _dedupe(slides: list, threshold: float = 0.85) -> list:
    """Drop short noise and slides whose text is almost identical to the previous one."""
    kept = []
    for s in slides:
        if len(s["text"]) < 15:
            continue
        if kept and SequenceMatcher(None, kept[-1]["text"], s["text"]).ratio() >= threshold:
            continue
        kept.append(s)
    return kept


def extract_slides_text(video_path, max_slides=OCR_MAX_SLIDES):
    import cv2

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frame_count / fps if fps > 0 else 0

    if duration <= 0:
        cap.release()
        return []

    # Spread samples across the full video, not SceneDetect windows.
    slide_limit = max(1, int(max_slides))
    sample_count = min(slide_limit, max(1, int(duration)))

    slides = []
    ui_labels = {
        "commands", "code", "text", "run all",
        "variables", "terminal", "ram", "disk",
    }

    try:
        reader = get_reader()

        for i in range(sample_count):
            sample_time = duration * (i + 0.5) / sample_count

            cap.set(cv2.CAP_PROP_POS_MSEC, sample_time * 1000)
            ok, frame = cap.read()

            if not ok or frame is None:
                continue

            height, width = frame.shape[:2]
            if width > 800:
                new_height = max(1, round(height * 800 / width))
                frame = cv2.resize(
                    frame,
                    (800, new_height),
                    interpolation=cv2.INTER_AREA,
                )

            results = reader.readtext(
                frame,
                detail=1,
                paragraph=False,
            )

            accepted = []

            for _bbox, detected_text, confidence in results:
                cleaned = " ".join(detected_text.split()).strip()
                normalized = re.sub(
                    r"[^a-z0-9]+", " ", cleaned.lower()
                ).strip()

                if confidence < 0.55:
                    continue
                if not re.search(r"[A-Za-z0-9]", cleaned):
                    continue
                if normalized in ui_labels:
                    continue
                if re.fullmatch(
                    r"(?:\d+\s*)?cells?\s+hidden", normalized
                ):
                    continue

                accepted.append(cleaned)

            text = " ".join(accepted).strip()

            if text:
                slides.append({
                    "time": sample_time,
                    "text": text,
                })

    finally:
        cap.release()

    return _dedupe(slides)


_LINE_START = re.compile(r"^\[(\d+(?:\.\d+)?)s -> ")


def merge_slides_into_transcript(transcript: str, slides: list) -> str:
    """Insert each slide's text just before the first spoken line at/after the moment the
    slide appeared, so the LLM sees slide and speech in the order they happened."""
    if not slides:
        return transcript
    lines = transcript.splitlines()
    pending = sorted(slides, key=lambda s: s["time"])
    out = []
    for line in lines:
        m = _LINE_START.match(line)
        start = float(m.group(1)) if m else None
        while pending and start is not None and pending[0]["time"] <= start:
            s = pending.pop(0)
            mm, ss = divmod(int(s["time"]), 60)
            out.append(f"[Slide shown at {mm:02d}:{ss:02d}]: {s['text']}")
        out.append(line)
    for s in pending:  # slides after the last spoken line
        mm, ss = divmod(int(s["time"]), 60)
        out.append(f"[Slide shown at {mm:02d}:{ss:02d}]: {s['text']}")
    return "\n".join(out)
