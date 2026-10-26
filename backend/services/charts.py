import base64
import io
import json
import re

import matplotlib
matplotlib.use("Agg")  # headless backend: safe in background threads on every OS
import matplotlib.pyplot as plt

from services.llm import _ollama_chat, get_model_name, strip_timestamps
from config import MAX_PROMPT_CHARS


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def extract_and_plot_trends(source_text: str) -> str:
    """Return a Markdown image for numeric data the lecture explicitly states, else ''."""
    prompt = (
        "You are a conservative chart-data extractor. Return "
        "has_data=true only when the lecture explicitly provides a "
        "coherent numerical dataset containing at least three data "
        "points from the same measurement, series, or comparison.\n"
        "Every category and value must be explicitly supported by "
        "the lecture, with a clear one-to-one relationship between "
        "each category and its numerical value.\n"
        "Never infer, calculate, estimate, or invent values. Do not "
        "treat isolated numbers, timestamps, slide numbers, class "
        "labels, feature names, or OCR artifacts as a dataset. "
        "Never assign arbitrary numbers such as 0, 1, 2 to categories.\n"
        "If the numerical values lack sufficient context, cannot be "
        "paired one-to-one, or do not form a coherent dataset, return "
        '{"has_data": false}.\n'
        "Otherwise return only JSON in this format: "
        '{"has_data": true, "title": "...", "x_label": "...", '
        '"y_label": "...", "x_data": ["A", "B", "C"], '
        '"y_data": [1, 2, 3]}.\n'
        "The x_data and y_data arrays must have equal lengths, "
        "with at least three pairs. Use only explicitly stated data.\n\n"
        f"Lecture:\n{strip_timestamps(source_text)[:MAX_PROMPT_CHARS]}"
    )
    try:
        content = _ollama_chat(
            system="You extract stated numeric data into strictly valid JSON.",
            user=prompt,
            temperature=0.1,
            json_mode=True,
            model=get_model_name(),
            num_predict=512,
        )
        match = re.search(r"\{[\s\S]*\}", content)
        data = json.loads(match.group(0) if match else content)

        x, y = data.get("x_data"), data.get("y_data")
        if (
            not data.get("has_data")
            or not isinstance(x, list) or not isinstance(y, list)
            or len(x) != len(y) or len(y) < 3
            or not all(_is_number(v) for v in y)
        ):
            return ""

        fig = plt.figure(figsize=(8, 5))
        try:
            numeric_x = all(_is_number(v) for v in x)
            if numeric_x:
                plt.plot(x, y, marker="o")
            else:
                plt.bar([str(v) for v in x], y)
                plt.xticks(rotation=30, ha="right")
            plt.title(data.get("title") or "Data from lecture")
            plt.xlabel(data.get("x_label") or "")
            plt.ylabel(data.get("y_label") or "")
            plt.grid(True, alpha=0.3)
            buf = io.BytesIO()
            plt.savefig(buf, format="png", bbox_inches="tight", dpi=110)
        finally:
            plt.close(fig)

        img = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"![{data.get('title') or 'Chart'}](data:image/png;base64,{img})"
    except Exception as e:
        print(f"Notice: chart skipped ({e})", flush=True)
        return ""
