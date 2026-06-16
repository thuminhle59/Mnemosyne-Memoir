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
  "summary_brief": {
    "context": str|null, "decisions": [str], "risk": str|null, "next_step": str|null
  },
  "key_points": [str], "decisions": [{"text": str, "quote": null}],
  "action_items": [{"task": str, "owner": str|null, "deadline": str|null,
                    "priority": "cao"|"trung bình"|"thấp", "quote": str|null}],
  "risks": [str], "open_questions": [str], "next_meeting": str|null
}"""

PRESERVE_ENGLISH_TERMS_RULE = (
    "NGUYÊN TẮC THUẬT NGỮ: GIỮ NGUYÊN chính xác tiếng Anh, tên riêng, tên sản phẩm, "
    "tên dự án, acronym và code term xuất hiện trong transcript; KHÔNG phiên âm, "
    "KHÔNG dịch, KHÔNG Việt hoá capitalization/hyphen. Ví dụ phải giữ đúng: "
    "Merchant, AgentBase, OpenClaw, MCP Server, QA, UAT, API, Pilot, Canary, Settlement."
)


def _prompt(transcript: str, date: str) -> str:
    return (
        "Bạn là thư ký họp chuyên nghiệp. Đọc transcript cuộc họp (tiếng Việt) bên dưới và "
        "trích xuất biên bản. Trả về DUY NHẤT một JSON hợp lệ, KHÔNG markdown, KHÔNG giải thích.\n"
        f"Ngày họp: {date}\n"
        f"{PRESERVE_ENGLISH_TERMS_RULE}\n"
        "owner là tên người được giao việc (suy từ nội dung). Với action_items, quote là câu nói gốc làm bằng chứng. "
        "Với decisions: CHỈ lấy các kết luận/chốt hướng đi đã thống nhất; decision có thể là câu tổng hợp giống summary "
        "nếu nó phản ánh đúng kết luận của cuộc họp. KHÔNG cần quote gốc cho decisions, đặt quote=null; timestamp sẽ do hệ thống tự ước lượng. "
        "Với summary_brief: Context: đúng 1 câu quan trọng nhất; Decisions: tối đa 2 câu quan trọng nhất và phải khớp decisions[] khi có; "
        "Risks: đúng 1 câu rủi ro/blocker quan trọng nhất và phải khớp risks[] khi có; Next steps: đúng 1 câu action/next step quan trọng nhất "
        "và phải khớp action_items[] khi có. Không đưa quote hoặc timestamp vào summary_brief. "
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
    prompt = (
        "Tóm tắt ngắn gọn ý chính, quyết định, việc cần làm trong đoạn họp sau "
        "(tiếng Việt).\n"
        f"{PRESERVE_ENGLISH_TERMS_RULE}\n" + chunk
    )
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
