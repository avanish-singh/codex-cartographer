"""
Research-paper analysis: extract PDF text, segment into sections, explain them,
and draft a methodology flowchart (Mermaid).

Uses an OpenAI-compatible chat API when OPENAI_API_KEY is set.
Falls back to heuristic sectioning (no LLM prose) when the key is missing.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SECTION_HINTS = (
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "methods",
    "methodology",
    "approach",
    "model",
    "architecture",
    "experiment",
    "experiments",
    "evaluation",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "future work",
    "references",
    "acknowledgment",
    "acknowledgement",
    "appendix",
)

SYSTEM_PROMPT = """You are a research-paper tutor. Given raw text extracted from a PDF, you:
1) Identify the main sections of the paper.
2) Explain each section in clear, simple language for a student or engineer.
3) Focus especially on Methodology / Methods: produce a step-by-step workflow.
4) Return a Mermaid flowchart for the methodology workflow.

Respond with ONLY valid JSON matching this schema:
{
  "title": "paper title if found else short guess",
  "summary": "3-5 sentence plain-English overview of the whole paper",
  "sections": [
    {
      "id": "abstract|introduction|methodology|experiments|results|discussion|conclusion|other",
      "title": "Section heading",
      "explanation": "2-4 sentence explanation of what this section says and why it matters",
      "key_points": ["bullet", "bullet"]
    }
  ],
  "methodology_steps": [
    {"id": "s1", "label": "short step name", "detail": "one sentence"}
  ],
  "methodology_mermaid": "flowchart TD\\n  A[Start] --> B[Next]..."
}

Rules for methodology_mermaid:
- Use Mermaid flowchart TD syntax only.
- Node labels must be short; avoid quotes and parentheses when possible.
- No markdown fences.
- Keep under 20 nodes.
"""


def extract_pdf_text(pdf_path: Path, *, max_chars: int = 60000) -> str:
    """Extract text from a PDF. Raises ValueError if empty/unreadable."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("pypdf is required for paper analysis. pip install pypdf") from exc

    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
        if sum(len(p) for p in parts) >= max_chars:
            break
    text = "\n".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 80:
        raise ValueError(
            "Could not extract enough text from this PDF "
            "(it may be a scanned image). Try a text-based PDF."
        )
    return text[:max_chars]


def _heading_score(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    low = s.lower().strip(" .:0123456789")
    if any(h in low for h in SECTION_HINTS):
        return True
    # ALL CAPS short headings
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7 and len(s) < 60:
        return True
    return False


def heuristic_sections(text: str) -> list[dict[str, Any]]:
    """Split text on likely headings when no LLM is available."""
    lines = text.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    current_title = "Preamble"
    current: list[str] = []
    for line in lines:
        if _heading_score(line) and current:
            blocks.append((current_title, current))
            current_title = line.strip()
            current = []
        else:
            current.append(line)
    if current:
        blocks.append((current_title, current))

    sections: list[dict[str, Any]] = []
    for title, body_lines in blocks[:12]:
        body = "\n".join(body_lines).strip()
        if len(body) < 40:
            continue
        sid = "other"
        low = title.lower()
        for key in (
            "abstract",
            "introduction",
            "related",
            "method",
            "experiment",
            "result",
            "discussion",
            "conclusion",
            "reference",
        ):
            if key in low:
                sid = "methodology" if key == "method" else key.rstrip("s")
                if key == "experiment":
                    sid = "experiments"
                if key == "result":
                    sid = "results"
                if key == "reference":
                    sid = "references"
                break
        excerpt = body[:500] + ("…" if len(body) > 500 else "")
        sections.append(
            {
                "id": sid,
                "title": title,
                "explanation": (
                    "This section was detected from the PDF layout. "
                    "Set OPENAI_API_KEY on the server for a full LLM explanation. "
                    f"Preview: {excerpt}"
                ),
                "key_points": [],
            }
        )
    if not sections:
        sections = [
            {
                "id": "document",
                "title": "Document",
                "explanation": text[:800] + ("…" if len(text) > 800 else ""),
                "key_points": [],
            }
        ]
    return sections


def heuristic_methodology_mermaid(sections: list[dict[str, Any]]) -> tuple[list[dict[str, str]], str]:
    method = next((s for s in sections if "method" in s["id"] or "method" in s["title"].lower()), None)
    steps = [
        {"id": "s1", "label": "Problem setup", "detail": "Define the research problem and assumptions."},
        {"id": "s2", "label": "Method / model", "detail": "Apply the proposed approach described in Methods."},
        {"id": "s3", "label": "Experiments", "detail": "Evaluate on datasets / benchmarks."},
        {"id": "s4", "label": "Results", "detail": "Report metrics and compare baselines."},
    ]
    if method:
        steps[1]["detail"] = method["explanation"][:180]
    mermaid = (
        "flowchart TD\n"
        "  A[Problem setup] --> B[Method / model]\n"
        "  B --> C[Experiments]\n"
        "  C --> D[Results & analysis]\n"
        "  D --> E[Conclusions]"
    )
    return steps, mermaid


def _llm_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


MIN_LLM_CHARS = 6000
MAX_LLM_ATTEMPTS = 4
OUTPUT_TOKEN_RESERVE = 3000
OMITTED_MARK = "\n\n[... part of the paper omitted to fit the model's token limit ...]\n\n"

_TOKEN_LIMIT_RE = re.compile(r"Limit (\d+), Requested (\d+)")
_REFERENCES_RE = re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE)


class _LLMHTTPError(Exception):
    def __init__(self, code: int, detail: str) -> None:
        super().__init__(f"LLM API error ({code}): {detail}")
        self.code = code
        self.detail = detail

    @property
    def too_large(self) -> bool:
        """True when the provider rejected the request for its size, not its content."""
        if self.code == 413 or "Request too large" in self.detail:
            return True
        return "context_length_exceeded" in self.detail


def condense_text(text: str, budget: int) -> str:
    """
    Fit paper text into `budget` characters.

    Drops the reference list first, then keeps the start (abstract, intro,
    method), a slice of the middle, and the end (results, conclusions).
    """
    if len(text) <= budget:
        return text
    matches = list(_REFERENCES_RE.finditer(text))
    if matches and matches[-1].start() > len(text) // 2:
        text = text[: matches[-1].start()].rstrip()
        if len(text) <= budget:
            return text

    room = max(budget - 2 * len(OMITTED_MARK), 0)
    head = int(room * 0.55)
    middle = int(room * 0.20)
    tail = room - head - middle
    mid_start = max(head, (len(text) - middle) // 2)
    return (
        text[:head]
        + OMITTED_MARK
        + text[mid_start : mid_start + middle]
        + OMITTED_MARK
        + text[len(text) - tail :]
    )


def _shrunk_budget(sent_chars: int, detail: str) -> int:
    """Pick a smaller character budget after a too-large rejection."""
    factor = 0.5
    match = _TOKEN_LIMIT_RE.search(detail)
    if match:
        limit, requested = int(match.group(1)), int(match.group(2))
        # Leave room for the reply: output tokens count against the same limit.
        usable = limit - OUTPUT_TOKEN_RESERVE if limit > 2 * OUTPUT_TOKEN_RESERVE else limit // 2
        if requested > 0:
            factor = min(0.95 * usable / requested, 0.8)
    return max(int(sent_chars * factor), MIN_LLM_CHARS)


def _post_chat(base: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    # Groq's Cloudflare edge rejects Python-urllib's default User-Agent (403 / 1010).
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "codex-cartographer/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise _LLMHTTPError(exc.code, detail) from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"LLM request failed: {exc}") from exc


def _parse_json_content(content: str) -> dict[str, Any]:
    """Parse the model's reply, tolerating code fences or stray text around the JSON."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM reply was not valid JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("LLM reply was not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    return data


def _call_llm(paper_text: str) -> tuple[dict[str, Any], bool]:
    """
    Ask the model for the analysis JSON.

    Returns (data, condensed). Free tiers cap tokens per request, so when the
    provider says the request is too large we retry with a condensed paper.
    """
    api_key = os.environ["OPENAI_API_KEY"].strip()
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    budget = len(paper_text)
    for attempt in range(MAX_LLM_ATTEMPTS):
        text = condense_text(paper_text, budget)
        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Analyze this research paper text and return the JSON object.\n\n"
                        f"{text}"
                    ),
                },
            ],
        }
        try:
            raw = _post_chat(base, api_key, payload)
        except _LLMHTTPError as exc:
            last_attempt = attempt == MAX_LLM_ATTEMPTS - 1
            if exc.too_large and not last_attempt and len(text) > MIN_LLM_CHARS:
                budget = _shrunk_budget(len(text), exc.detail)
                continue
            raise ValueError(str(exc)) from exc
        content = raw["choices"][0]["message"]["content"]
        return _parse_json_content(content), len(text) < len(paper_text)
    raise ValueError("LLM request failed: paper is too large for the model's token limit")


def _normalize(data: dict[str, Any], *, mode: str, source: str) -> dict[str, Any]:
    sections = data.get("sections") or []
    clean_sections = []
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        clean_sections.append(
            {
                "id": str(sec.get("id") or f"sec{i}"),
                "title": str(sec.get("title") or f"Section {i + 1}"),
                "explanation": str(sec.get("explanation") or ""),
                "key_points": [str(x) for x in (sec.get("key_points") or [])][:8],
            }
        )
    steps = data.get("methodology_steps") or []
    clean_steps = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        clean_steps.append(
            {
                "id": str(step.get("id") or f"s{i + 1}"),
                "label": str(step.get("label") or f"Step {i + 1}"),
                "detail": str(step.get("detail") or ""),
            }
        )
    mermaid = str(data.get("methodology_mermaid") or "").strip()
    if mermaid.startswith("```"):
        mermaid = re.sub(r"^```(?:mermaid)?\n?", "", mermaid)
        mermaid = re.sub(r"\n?```$", "", mermaid)
    if not mermaid:
        clean_steps, mermaid = heuristic_methodology_mermaid(clean_sections)
    return {
        "version": 1,
        "mode": mode,  # llm | heuristic
        "source_file": source,
        "title": str(data.get("title") or Path(source).stem),
        "summary": str(data.get("summary") or ""),
        "sections": clean_sections,
        "methodology_steps": clean_steps,
        "methodology_mermaid": mermaid,
        "llm_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini") if mode == "llm" else None,
    }


def analyze_paper(pdf_path: Path, *, filename: str | None = None) -> dict[str, Any]:
    """
    Full paper analysis pipeline.

    Returns a JSON-serializable dict for the paper-session UI.
    """
    source = filename or pdf_path.name
    text = extract_pdf_text(pdf_path)

    if _llm_enabled():
        try:
            data, condensed = _call_llm(text)
            out = _normalize(data, mode="llm", source=source)
            out["input_condensed"] = condensed
            return out
        except Exception as exc:  # noqa: BLE001 — fall back rather than fail the upload
            sections = heuristic_sections(text)
            steps, mermaid = heuristic_methodology_mermaid(sections)
            out = _normalize(
                {
                    "title": Path(source).stem,
                    "summary": (
                        f"LLM analysis failed ({exc}). Showing heuristic section split instead. "
                        "Check OPENAI_API_KEY / OPENAI_MODEL on the server."
                    ),
                    "sections": sections,
                    "methodology_steps": steps,
                    "methodology_mermaid": mermaid,
                },
                mode="heuristic",
                source=source,
            )
            out["error"] = str(exc)
            return out

    sections = heuristic_sections(text)
    steps, mermaid = heuristic_methodology_mermaid(sections)
    return _normalize(
        {
            "title": Path(source).stem,
            "summary": (
                "Structural preview of the paper (no LLM key configured). "
                "Set the OPENAI_API_KEY environment variable to enable full section explanations "
                "and a detailed methodology flowchart."
            ),
            "sections": sections,
            "methodology_steps": steps,
            "methodology_mermaid": mermaid,
        },
        mode="heuristic",
        source=source,
    )


def save_analysis(job_dir: Path, analysis: dict[str, Any]) -> Path:
    path = job_dir / "paper_analysis.json"
    path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    return path
