import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from services.llm import get_model_name, _ollama_chat

_embedder = None
dimension = 384  # Output dimension of all-MiniLM-L6-v2

RAG_SYSTEM = (
    "You are a lecture tutor. Answer ONLY from the lecture excerpts provided. "
    "If the excerpts do not contain the answer, reply exactly: "
    "\"The lecture material doesn't cover this.\" Do not use outside knowledge. "
    "Excerpts begin with timestamps like [12.34s -> 15.67s]; when you state a fact, "
    "mention the nearest timestamp in brackets, e.g. [about 12s]. Be concise."
)


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


class RAGStore:
    def __init__(self):
        self.index = faiss.IndexFlatL2(dimension)
        self.chunks = []

    def add_document(self, text: str, chunk_words: int = 220, overlap: int = 40):
        """Chunk by words with overlap. Keep the timestamps so answers can cite them."""
        embedder = get_embedder()
        words = text.split()
        step = max(1, chunk_words - overlap)
        new_chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i:i + chunk_words])
            if chunk:
                new_chunks.append(chunk)
            if i + chunk_words >= len(words):
                break
        if new_chunks:
            embeddings = embedder.encode(new_chunks)
            self.index.add(np.array(embeddings).astype("float32"))
            self.chunks.extend(new_chunks)

    def query(self, question: str, top_k: int = 4, history: list | None = None) -> str:
        if not self.chunks:
            return "No context available."

        embedder = get_embedder()
        q_emb = np.array(embedder.encode([question])).astype("float32")
        k = min(top_k, len(self.chunks))                  # never ask FAISS for more than exist
        _, indices = self.index.search(q_emb, k)
        picked = [self.chunks[i] for i in indices[0] if 0 <= i < len(self.chunks)]  # skip -1 padding
        context = "\n\n---\n\n".join(picked)

        convo = ""
        for turn in (history or [])[-6:]:
            who = "Student" if turn.get("role") == "user" else "Tutor"
            convo += f"{who}: {str(turn.get('content', ''))[:600]}\n"
        prompt = (
            f"Lecture excerpts:\n{context}\n\n"
            + (f"Conversation so far:\n{convo}\n" if convo else "")
            + f"Student question: {question}\nAnswer:"
        )
        return _ollama_chat(
            system=RAG_SYSTEM, user=prompt, temperature=0.2, model=get_model_name()
        )
