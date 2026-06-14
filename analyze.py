"""Turn a transcript into a validated MeetingReport.

Uses a primary chat model with a stricter-nudge retry, then a fallback model
(config.SUMMARY_MODEL / config.EXTRACT_FALLBACK_MODEL — do not assume specific
model names here). Long transcripts are summarized map-reduce. The
transcript is attached by analyze() itself; the LLM does not echo it.
"""
import json
import re
import config
import llm
from models import MeetingReport

_SCHEMA_HINT = """{
  "title": str, "date": str, "duration_min": int|null, "summary": str,
  "key_points": [str], "decisions": [{"text": str, "quote": str|null}],
  "action_items": [{"task": str, "owner": str|null, "deadline": str|null,
                    "priority": "cao"|"trung bình"|"thấp", "quote": str|null}],
  "risks": [str], "open_questions": [str], "next_meeting": str|null
}"""


def _prompt(transcript: str, date: str) -> str:
    return (
        "Bạn là thư ký họp chuyên nghiệp. Đọc transcript cuộc họp (tiếng Việt) bên dưới và "
        "trích xuất biên bản. Trả về DUY NHẤT một JSON hợp lệ, KHÔNG markdown, KHÔNG giải thích.\n"
        f"Ngày họp: {date}\n"
        "owner là tên người được giao việc (suy từ nội dung). quote là câu nói gốc làm bằng chứng. "
        "priority chọn trong: cao, trung bình, thấp.\n"
        f"Schema:\n{_SCHEMA_HINT}\n\nTranscript:\n{transcript}"
    )


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response, tolerant of code
    fences and trailing prose/extra objects (uses raw_decode)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    first = text.find("{")
    if first == -1:
        raise ValueError("no JSON object in LLM output")
    obj, _ = json.JSONDecoder().raw_decode(text[first:])
    return obj


def _chunks(transcript: str, size: int) -> list[str]:
    """Split into <=size pieces by line; hard-split any single overlong line."""
    out: list[str] = []
    cur = ""
    for ln in transcript.splitlines():
        while len(ln) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(ln[:size])
            ln = ln[size:]
        if cur and len(cur) + len(ln) > size:
            out.append(cur)
            cur = ""
        cur += ln + "\n"
    if cur:
        out.append(cur)
    return out


def _map_chunk(chunk: str) -> str:
    """Summarize one chunk; tolerate model failure so one bad chunk can't abort
    the whole meeting (tries primary then fallback model, else returns '')."""
    prompt = ("Tóm tắt ngắn gọn ý chính, quyết định, việc cần làm trong đoạn họp sau "
              "(tiếng Việt):\n" + chunk)
    for model in (config.SUMMARY_MODEL, config.EXTRACT_FALLBACK_MODEL):
        try:
            return llm.chat(prompt, model=model)
        except Exception:  # noqa: BLE001 - map phase is best-effort
            continue
    return ""


def _summarize(transcript: str, date: str) -> dict:
    """Try primary model, retry once with a stricter nudge, then fall back."""
    prompt = _prompt(transcript, date)
    last_err: Exception | None = None
    for attempt, model in [(0, config.SUMMARY_MODEL), (1, config.SUMMARY_MODEL), (2, config.EXTRACT_FALLBACK_MODEL)]:
        p = prompt + "\n\nLƯU Ý: Lần trước trả sai. CHỈ trả JSON thuần." if attempt == 1 else prompt
        try:
            return _extract_json(llm.chat(p, model=model))
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            continue
    raise ValueError("LLM did not return valid JSON after retries + fallback") from last_err


def analyze(transcript: str, date: str) -> MeetingReport:
    if len(transcript) <= config.MAP_REDUCE_CHAR_THRESHOLD:
        data = _summarize(transcript, date)
    else:
        notes = [_map_chunk(c) for c in _chunks(transcript, config.MAP_REDUCE_CHAR_THRESHOLD)]
        data = _summarize("\n".join(n for n in notes if n), date)
    data["full_transcript"] = transcript
    data.setdefault("date", date)
    return MeetingReport.model_validate(data)
