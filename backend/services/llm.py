import json
import re
import requests

from config import (
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    MAX_PROMPT_CHARS,
)

from services.thermal_agent import thermal_agent
from services.cleaner import clean_markdown_notes, sanitize_mermaid


def get_model_name() -> str:
    """
    Select an Ollama model using the thermal agent's current state.

    The current temperature value is estimated rather than read from a
    hardware temperature sensor. The agent selects between the configured
    primary and compact Ollama models.
    """
    decision = thermal_agent.select_model()
    model = decision["selected_model"]
    temp = decision["telemetry"]["primary_temp_c"]
    risk = decision["telemetry"]["throttling_risk"]
    print(
        f"[Thermal Model Selector] Estimated Temp: {temp} C | Status: {risk} | "
        f"Dispatched: {model} ({decision['model_tier']})",
        flush=True,
    )
    return model


def _ollama_chat(
    system: str,
    user: str,
    temperature: float = 0.3,
    json_mode: bool = False,
    model: str = None,
    num_predict: int = 8192,
) -> str:
    """
    Calls Ollama's native chat API with a 16K context window and thinking
    disabled, so long transcripts are not silently truncated and the model
    does not burn its token budget on hidden reasoning.
    """
    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {
            "num_ctx": 16384,
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    if json_mode:
        payload["format"] = "json"

    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=900)
    resp.raise_for_status()
    data = resp.json()
    content = ((data.get("message") or {}).get("content") or "").strip()

    print(
        f"[Ollama] Prompt tokens: {data.get('prompt_eval_count', 'unknown')} | "
        f"Output tokens: {data.get('eval_count', 'unknown')}",
        flush=True,
    )

    if not content:
        raise RuntimeError("Ollama returned empty content.")
    return content


# ---------------------------------------------------------------------------
# Input preparation: keep prompts inside the context window
# ---------------------------------------------------------------------------
_TS_PREFIX = re.compile(r"^\[\d+(?:\.\d+)?s -> \d+(?:\.\d+)?s\]\s*", re.MULTILINE)


def strip_timestamps(text: str) -> str:
    """Remove the Whisper '[12.34s -> 15.67s]' prefixes (about a third of the tokens)."""
    return _TS_PREFIX.sub("", text or "")


def split_for_context(text: str, max_chars: int = MAX_PROMPT_CHARS) -> list:
    """Split on line boundaries into pieces of at most max_chars."""
    chunks, current, size = [], [], 0
    for line in text.splitlines():
        if size + len(line) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _notes_for_chunk(chunk: str, part: int, total: int, model: str) -> str:
    part_note = (
        f"This is part {part} of {total} of a longer lecture; write notes for "
        "this part only, without a conclusion for the whole lecture.\n\n"
        if total > 1 else ""
    )
    prompt = (
        "Create comprehensive, well-structured academic study notes from "
        "the following lecture material. Preserve the instructor's spoken "
        "explanations, definitions, reasoning, examples, and conclusions. "
        "Integrate slide text where useful; do not merely describe the slides. "
        "Use descriptive headings, clear explanations, bullet points, "
        "bold key terms, and Markdown tables where appropriate. "
        "Avoid unnecessary repetition. Before finalizing, audit every "
        "numerical worked example. Verify the method, the selected data "
        "or class interval, the meaning of each variable, every formula "
        "substitution, the intermediate arithmetic, and the final answer. "
        "Ensure the displayed formula matches the calculation performed. "
        "For grouped-frequency tables, the median class is the first "
        "class whose cumulative frequency reaches or exceeds half the "
        "total frequency. Do not select a later class incorrectly. "
        "If the supplied information is insufficient to verify a result, "
        "state that limitation rather than inventing values. "
        "Use plain-text equations suitable for a basic Markdown viewer. "
        "Do not output LaTeX commands, backslash-based math delimiters, "
        "or dollar-delimited math. Use readable symbols, parentheses, "
        "division slashes, and multiplication signs instead.\n\n"
        f"{part_note}"
        f"Lecture transcript and slide text:\n{chunk}\n\n"
        "Write the study notes now."
    )
    print(
        f"[Notes] part {part}/{total} model={model}; input characters={len(prompt)}",
        flush=True,
    )
    return _ollama_chat(
        system=(
            "You are an expert academic tutor who produces accurate, "
            "detailed, self-contained study notes from lecture material."
        ),
        user=prompt,
        temperature=0.3,
        model=model,
    )


def generate_notes(transcript: str) -> str:
    text = strip_timestamps(transcript)
    chunks = split_for_context(text)
    model = get_model_name()
    parts = [
        clean_markdown_notes(_notes_for_chunk(c, i, len(chunks), model))
        for i, c in enumerate(chunks, 1)
    ]
    return "\n\n".join(parts)


def generate_diagrams(source_text: str) -> str:
    """Build one Mermaid flowchart. Pass the generated NOTES (short, clean) rather than
    the raw transcript so the diagram reflects the lecture's structure."""
    prompt = (
        "Create ONE Mermaid diagram that faithfully represents the study notes. "
        "Use a flowchart for a genuine process or pipeline. For a theoretical "
        "lecture, create a compact concept map around the central topic.\n"
        "Rules: first line exactly 'flowchart TD'; use 6 to 12 nodes total, "
        "never more than 12. Node ids must be short words or letters. Every "
        "label must contain 2 to 6 words inside double quotes, for example "
        'A["Predictive Models"]. Do not use parentheses, colons, or double '
        "quotes inside labels.\n"
        "Connect concepts only when their relationship is supported by the "
        "notes. Use arrows for genuine sequence, dependency, or relationships "
        "explicitly explained in the lecture. For theoretical topics, use "
        "branches from a central concept instead of forcing unrelated ideas "
        "into a linear chain. Do not make independent concepts sequential. "
        "Keep examples under their relevant concepts; do not connect examples "
        "to each other or repeat them unnecessarily.\n"
        "Represent distinctions and hierarchies accurately. For example, "
        "classification and regression may be separate branches of supervised "
        "learning when supported by the notes; do not place unsupervised "
        "learning between them as a sequential step. Do not invent concepts, "
        "steps, or relationships.\n"
        "Output only valid Mermaid syntax, without explanation or code fences. "
        "If the notes contain no suitable process or conceptual hierarchy, "
        "output only NONE.\n\n"
        f"Notes:\n{source_text[:MAX_PROMPT_CHARS]}"
    )
    model = get_model_name()
    try:
        raw = _ollama_chat(
            system="You write valid Mermaid.js flowchart definitions and nothing else.",
            user=prompt, temperature=0.2, model=model,
        )
    except Exception as e:
        print(f"[Diagrams] Skipped: {e}", flush=True)
        return ""
    if raw.strip().upper().startswith("NONE"):
        return ""
    return sanitize_mermaid(raw)


def validate_quiz(parsed: dict, difficulty: str, min_questions: int = 3) -> dict:
    """Keep only well-formed questions: 4 distinct options, answer is one of them."""
    raw = parsed.get("questions") if isinstance(parsed, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("Quiz JSON has no 'questions' list.")

    good, seen = [], set()
    for q_index, q in enumerate(raw, 1):
        if not isinstance(q, dict) or not isinstance(q.get("options"), list):
            print(
                f"[Quiz validation] Candidate {q_index} rejected: "
                "malformed question or options.",
                flush=True,
            )
            continue
        text = str(q.get("question", "")).strip()
        options = [str(o).strip() for o in q["options"] if str(o).strip()]
        folded = [o.casefold() for o in options]
        answer = str(q.get("correct_answer", "")).strip()

        # Accept "B" / "Option B" style answers by mapping the letter to its option.
        letter = answer.rstrip(".) ").split()[-1].upper() if answer else ""
        if answer.casefold() not in folded and len(letter) == 1 and letter in "ABCD":
            idx = "ABCD".index(letter)
            if idx < len(options):
                answer = options[idx]

        reasons = []

        if not text:
            reasons.append("empty question")
        if text.casefold() in seen:
            reasons.append("duplicate question")
        if len(options) != 4:
            reasons.append(f"expected 4 options, got {len(options)}")
        if len(set(folded)) != 4:
            reasons.append("duplicate option text")
        if answer.casefold() not in folded:
            reasons.append("correct answer does not match an option")

        if reasons:
            print(
                f"[Quiz validation] Candidate {q_index} rejected: "
                f"{', '.join(reasons)} | question={text!r}",
                flush=True,
            )
            continue

        seen.add(text.casefold())
        good.append({
            "id": len(good) + 1,
            "difficulty": difficulty,
            "question": text,
            "options": options,
            "correct_answer": options[folded.index(answer.casefold())],
            "explanation": str(q.get("explanation", "")).strip(),
        })

    if len(good) < min_questions:
        raise ValueError(f"Only {len(good)} valid questions after validation.")
    return {"difficulty": difficulty, "questions": good}

def review_quiz(source: str, quiz: dict, model: str) -> dict:
    """Review quiz correctness and semantic ambiguity before acceptance."""
    review_prompt = (
        "Audit every question in the candidate quiz against the spoken "
        "lecture. Act as a strict quality reviewer, not as a quiz generator.\n"
        "Check every question, option, correct answer, and explanation.\n"
        "Verify that:\n"
        "1. The correct answer is supported by the lecture or follows "
        "from a correct calculation using its data.\n"
        "2. Each numerical explanation uses the correct formula, values, "
        "substitutions, and arithmetic. Recalculate independently; do "
        "not trust the candidate's explanation.\n"
        "3. Every formula is appropriate for the concept being tested. "
        "In particular, do not confuse mean, median, and mode formulas.\n"
        "4. Exactly one option is defensibly correct. Detect options "
        "that are equivalent in meaning or differ only by rounding.\n"
        "5. The explanation supports the selected answer and does not "
        "contradict itself or the lecture.\n"
        "6. The quiz tests the lecture's major concepts and does not "
        "confuse frequencies, cumulative frequencies, or class intervals.\n"
        "Use the spoken lecture as the evidence. Do not assume that the "
        "candidate answer is correct merely because it is marked correct. "
        "If any question has a substantive error or you are uncertain, "
        "reject the quiz and identify the affected question.\n\n"
        "Return only JSON in exactly this shape:\n"
        '{"passed": true, "issues": []}\n'
        "If the quiz has any issue, return passed=false and provide a "
        "concise issue for each affected question, using this shape:\n"
        '{"passed": false, "issues": [{"question_id": 3, '
        '"reason": "The explanation uses incorrect arithmetic."}]}\n\n'
        f"Spoken lecture:\n{source}\n\n"
        f"Candidate quiz:\n{json.dumps(quiz, ensure_ascii=False)}"
    )

    content = _ollama_chat(
        system=(
            "You are a strict educational assessment auditor. "
            "Independently verify answers and calculations. "
            "Return only the requested JSON."
        ),
        user=review_prompt,
        temperature=0.0,
        json_mode=True,
        model=model,
        num_predict=1536,
    )

    match = re.search(r"\{[\s\S]*\}", content)
    result = json.loads(match.group(0) if match else content)

    if (
        not isinstance(result, dict)
        or not isinstance(result.get("passed"), bool)
        or not isinstance(result.get("issues"), list)
    ):
        raise ValueError("Quiz reviewer returned an invalid JSON structure.")

    issues = result["issues"]

    if not result["passed"] and not issues:
        issues = [{
            "reason": "Reviewer rejected the quiz without providing details."
        }]

    return {
        "passed": result["passed"] and not issues,
        "issues": issues,
    }


def generate_quiz(transcript: str, difficulty: str = "medium", attempts: int = 3) -> str:
    difficulty = difficulty.lower() if difficulty.lower() in ("easy", "medium", "hard") else "medium"
    transcript_text = strip_timestamps(transcript)

    # Quiz questions should use spoken content, not fragmented OCR slide text.
    spoken_lines = [
        line
        for line in transcript_text.splitlines()
        if not re.match(
            r"^\s*\[Slide shown at \d{2}:\d{2}\]:",
            line,
        )
    ]

    source = "\n".join(spoken_lines).strip()[:MAX_PROMPT_CHARS]
    diff_note = {
        "easy": (
            "Level: EASY. Test recall of one stated fact per question: a definition, "
            "a name, a number, or a single step. Wrong options are clearly different."
        ),
        "medium": (
            "Level: MEDIUM. Test understanding: why something works, how two ideas "
            "differ, or which concept applies to a short described situation."
        ),
        "hard": (
            "Level: HARD. Test reasoning: give a new scenario or a small calculation "
            "that is NOT stated in the lecture and require applying two or more "
            "ideas from it. Wrong options must be plausible mistakes."
        ),
    }[difficulty]

    prompt = (
        "Based on the lecture below, write exactly 8 multiple-choice questions.\n"
        f"{diff_note}\n"
        "Rules: each question must have exactly 4 different options and "
        "exactly ONE unambiguously correct answer. Options must differ in "
        "meaning, not just wording. Never include two equivalent answers "
        "or two mathematically equivalent options. The correct_answer "
        "must exactly match one of the options. Cover different parts "
        "of the lecture and ignore garbled OCR text.\n"
        "Question planning: First identify the main concepts explicitly "
        "taught in the lecture. Distribute the 8 questions across those "
        "concepts rather than overfocusing on supporting facts. If the "
        "lecture teaches mean, median, and mode, use questions 1-2 for "
        "mean, 3-5 for median, and 6-8 for mode. Include at least one "
        "calculation question for each measure when the lecture provides "
        "enough information. For other lectures, apply the same principle "
        "by distributing questions across the major concepts actually "
        "taught, including application questions where appropriate.\n"
        "Use precise terminology in every explanation. Median questions "
        "must use median-class and cumulative-frequency terminology; "
        "mode questions must use modal-class and adjacent-frequency "
        "terminology. Never confuse the two. If a calculated answer is "
        "rounded, explicitly state the required precision in the question "
        "and keep all options at that precision.\n"
        "For numerical questions, independently verify the formula, "
        "variable values, substitutions, arithmetic, and final answer. "
        "The explanation must support the selected answer and use the "
        "same valid formula. Never invent or alter a formula. If you "
        "cannot verify a calculation confidently, use a conceptual "
        "question instead. Keep each explanation to 1-2 sentences "
        "to avoid unnecessarily long output.\n"
        "For numerical answer options, use consistent decimal precision "
        "and units. Never include a distractor equivalent to the correct "
        "answer when rounded to another precision, unless the question "
        "explicitly asks about rounding. If rounding is intended, state "
        "the required precision in the question and keep all options "
        "consistent with it.\n\n"
        "Return only valid JSON in this shape, with exactly 8 questions:\n"
        '{"questions": [{"question": "...", "options": ["...", "...", "...", "..."], '
        '"correct_answer": "...", "explanation": "..."}]}\n\n'
        f"Lecture:\n{source}"
    )

    base_prompt = prompt
    model = get_model_name()
    last_error = None
    for attempt in range(1, attempts + 1):
        content = _ollama_chat(
            system="You are a quiz generator that outputs strictly valid JSON.",
            user=prompt,
            temperature=0.2 if attempt == 1 else 0.5,
            json_mode=True,
            model=model,
            num_predict=4096,
        )
        match = re.search(r"\{[\s\S]*\}", content)
        try:
            quiz = validate_quiz(
                json.loads(match.group(0) if match else content),
                difficulty,
                min_questions=8,
            )

            if len(quiz["questions"]) != 8:
                raise ValueError(
                    f"Expected exactly 8 valid questions, "
                    f"got {len(quiz['questions'])}."
                )

            try:
                review = review_quiz(source, quiz, model)

                if not review["passed"]:
                    print(
                        "[Quiz] Advisory review flagged candidate: "
                        + json.dumps(review["issues"], ensure_ascii=False),
                        flush=True,
                    )
                else:
                    print(
                        "[Quiz] Advisory review passed; "
                        "independent correctness is not guaranteed.",
                        flush=True,
                    )

            except Exception as review_error:
                print(
                    f"[Quiz] Advisory review unavailable: {review_error}",
                    flush=True,
                )

            return json.dumps(quiz)
        except Exception as e:
            last_error = e
            print(f"[Quiz] attempt {attempt}/{attempts} rejected: {e}", flush=True)
    raise RuntimeError(f"Quiz generation failed after {attempts} attempts: {last_error}")
