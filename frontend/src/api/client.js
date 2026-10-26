import axios from "axios";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 45000,
  headers: {
    "Content-Type": "application/json",
  },
});

export default api;

export async function downloadLecturePdf(lectureId) {
  const res = await api.get(`/lectures/${lectureId}/export`, {
    responseType: "blob",
    timeout: 120000, // PDF rendering can take a while
  });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = `lecture_${lectureId}_notes.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Axios turns a failed blob request's JSON error into a Blob; read the message back out.
export async function describeError(err, fallback = "Request failed.") {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try { return JSON.parse(await data.text()).detail || fallback; } catch { return fallback; }
  }
  return data?.detail || err?.message || fallback;
}
