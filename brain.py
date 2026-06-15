"""The reasoning layer over the meeting memory.

Pure-ish functions: pull data from db/retrieve, call llm, return Pydantic / dicts.
All LLM calls go through llm.chat with a primary + fallback model so one model
hiccup never aborts an ingest. Every function is testable with a mock llm.chat.

Flows:
  extract_facts        transcript+report -> KnowledgeFact[]
  detect_contradictions new facts vs active facts of same subject -> Contradiction[]
  ingest               full pipeline: transcribe? -> analyze -> facts -> save -> contradictions
  ask                  Historical Recall Q&A (see ask section)
  digest / follow_up   added later
"""
import datetime as _dt
import json
import re

import config
import llm
import db
import analyze
import transcribe
import retrieve as retrieve_mod
from models import (
    MeetingReport, KnowledgeFact, FactList, Contradiction, Answer, Citation,
)

_FACT_SCHEMA = """{"facts": [
  {"type": "quyết định"|"fact"|"cam kết"|"số liệu"|"giả định"|"rủi ro",
   "subject": str, "statement": str, "quote": str|null}
]}"""


def _extract_json(text: str) -> dict:
    """Tolerant JSON-object extraction (shared shape with analyze._extract_json)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    first = text.find("{")
    if first == -1:
        raise ValueError("no JSON object in LLM output")
    obj, _ = json.JSONDecoder().raw_decode(text[first:])
    return obj


def _chat_json(prompt: str, models: tuple[str, ...]) -> dict:
    """Call models in order; return first parseable JSON object, else raise."""
    last: Exception | None = None
    for model in models:
        try:
            return _extract_json(llm.chat(prompt, model=model))
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            continue
        except Exception as e:  # noqa: BLE001 - network/model errors -> try next
            last = e
            continue
    raise ValueError(f"no valid JSON from models {models}") from last


# ---------------------------------------------------------------- correct_terms (STT layer 3)

def _effective_glossary() -> str:
    """Default glossary + org/team terms taught via the training guide (db)."""
    terms = [config.STT_GLOSSARY]
    try:
        extra = db.glossary_terms()
        if extra:
            terms.append(", ".join(extra))
    except Exception:  # noqa: BLE001 - DB not ready
        pass
    return ", ".join(t for t in terms if t)


def _correct_prompt(text: str) -> str:
    return (
        "Dưới đây là transcript do nhận dạng giọng nói tạo ra, có thể nghe nhầm DANH TỪ RIÊNG.\n"
        f"Glossary tên đúng (CHỈ là gợi ý, có thể KHÔNG xuất hiện trong audio): {_effective_glossary()}\n"
        "Nhiệm vụ: CHỈ sửa những danh từ riêng bị nghe nhầm cho khớp glossary KHI NGỮ CẢNH "
        "cho thấy đúng là nó. Nếu transcript nói về chủ đề khác và không liên quan glossary, "
        "GIỮ NGUYÊN, KHÔNG thêm thắt. Tuyệt đối KHÔNG diễn giải lại, KHÔNG tóm tắt, KHÔNG đổi "
        "từ thường — giữ nguyên 100% nội dung, chỉ thay đúng các tên bị sai.\n"
        'Trả về DUY NHẤT JSON: {"corrected": "<transcript đã sửa>"}\n\n'
        f"Transcript:\n{text}"
    )


def extract_glossary_terms(guide_text: str) -> list[str]:
    """LLM-extract org/team/project proper nouns & terminology from a training guide."""
    if not guide_text.strip():
        return []
    prompt = (
        "Đây là tài liệu hướng dẫn của một tổ chức/team. Hãy TRÍCH danh sách các DANH TỪ RIÊNG "
        "và THUẬT NGỮ đặc thù (tên sản phẩm, dự án, hệ thống, team, viết tắt nội bộ) — những từ "
        "mà hệ thống nhận dạng giọng nói dễ nghe nhầm. Bỏ qua từ thông thường.\n"
        'Trả về DUY NHẤT JSON: {"terms": [str, ...]}\n\n'
        f"Tài liệu:\n{guide_text[:12000]}"
    )
    try:
        data = _chat_json(prompt, (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
    except ValueError:
        return []
    terms = data.get("terms", [])
    return [t.strip() for t in terms if isinstance(t, str) and t.strip()]


def learn_glossary(guide_text: str) -> list[str]:
    """Extract terms from a guide and persist them; returns the terms saved."""
    terms = extract_glossary_terms(guide_text)
    for t in terms:
        db.add_glossary(t)
    return terms


def correct_terms(text: str) -> str:
    """Context-aware proper-noun fix via LLM. Safe on unknown topics (won't force
    glossary terms). Guardrailed: if the model returns nothing or rewrites too much
    (length drifts far from the original), the original is kept."""
    if not config.STT_LLM_CORRECT or not text.strip():
        return text
    try:
        data = _chat_json(_correct_prompt(text),
                          (config.STT_CORRECT_MODEL, config.REASONING_FALLBACK_MODEL))
    except ValueError:
        return text
    out = (data.get("corrected") or "").strip()
    if not out:
        return text
    ratio = len(out) / max(len(text), 1)
    if ratio < 0.6 or ratio > 1.6:   # over-edit / truncation guard -> keep original
        return text
    return out


# ---------------------------------------------------------------- extract_facts

def _facts_prompt(report: MeetingReport, transcript: str) -> str:
    return (
        "Bạn là trợ lý phân tích cuộc họp. Từ biên bản và transcript bên dưới, hãy "
        "TRÍCH các 'fact nguyên tử' — mỗi fact là MỘT phát biểu độc lập, đã chuẩn hoá, "
        "thuộc các loại: quyết định, fact, cam kết, số liệu, giả định, rủi ro.\n"
        "Mỗi fact cần có 'subject' ngắn gọn (chủ đề, ví dụ 'ngày launch', 'ngân sách Q3') "
        "để sau này đối chiếu xuyên cuộc họp, và 'quote' là câu gốc làm bằng chứng (nếu có).\n"
        "Trả về DUY NHẤT JSON hợp lệ, KHÔNG markdown, KHÔNG giải thích.\n"
        f"Schema:\n{_FACT_SCHEMA}\n\n"
        f"Tóm tắt: {report.summary}\n"
        f"Transcript:\n{transcript}"
    )


def extract_facts(report: MeetingReport, transcript: str) -> list[KnowledgeFact]:
    """One LLM pass → atomic KnowledgeFact[]. Best-effort: returns [] on failure
    so a meeting still ingests (report is the source of truth) even if extraction fails."""
    try:
        data = _chat_json(
            _facts_prompt(report, transcript),
            (config.EXTRACT_MODEL, config.EXTRACT_FALLBACK_MODEL),
        )
    except ValueError:
        return []
    try:
        return FactList.model_validate(data).facts
    except Exception:  # noqa: BLE001 - shape drift -> no facts rather than crash
        return []


# ---------------------------------------------------------------- contradictions

def _contra_prompt(new: KnowledgeFact, old_subject: str, old_statement: str) -> str:
    return (
        "Hai phát biểu sau đến từ các cuộc họp khác nhau. Chúng có MÂU THUẪN không "
        "(nghịch nhau, KHÔNG THỂ cùng đúng về cùng một việc)? Lưu ý: chỉ coi là mâu thuẫn "
        "nếu cùng nói về MỘT việc/chủ đề mà giá trị/kết luận khác nhau; nếu là hai việc "
        "khác nhau thì KHÔNG mâu thuẫn.\n"
        f"Phát biểu CŨ (chủ đề '{old_subject}'): {old_statement}\n"
        f"Phát biểu MỚI (chủ đề '{new.subject}'): {new.statement}\n"
        'Trả về DUY NHẤT JSON: {"contradicts": true|false, "explanation": str, '
        '"severity": "cao"|"trung bình"|"thấp"}'
    )


def detect_contradictions(new_facts: list[KnowledgeFact]) -> list[Contradiction]:
    """For each new fact, compare with EARLIER active facts of the same subject.
    On conflict: record a Contradiction, mark the older fact 'đã thay thế', and
    surface it (caller shows a proactive warning). Runs at ingest time."""
    found: list[Contradiction] = []
    all_active = [f for f in db.all_facts(limit=10000) if f.status == "hiệu lực"]
    for nf in new_facts:
        if nf.source_meeting_id is None:
            continue
        # Candidates = earlier active facts whose subject SHARES a token with this one.
        # Exact-subject matching misses conflicts when the model words the same topic
        # differently across meetings ("ngày launch" vs "ngày ra mắt"); the LLM verdict
        # below filters out coincidental token overlaps.
        nf_tokens = retrieve_mod._tokens(nf.subject)
        candidates = [
            f for f in all_active
            if f.meeting_id != nf.source_meeting_id
            and (retrieve_mod._tokens(f.subject) & nf_tokens)
        ]
        for old in candidates:
            if old.statement.strip() == nf.statement.strip():
                continue  # identical restatement, not a conflict
            try:
                verdict = _chat_json(
                    _contra_prompt(nf, old.subject, old.statement),
                    (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL),
                )
            except ValueError:
                continue
            if not verdict.get("contradicts"):
                continue
            # find the new fact's row id (same subject+statement+meeting)
            new_id = next(
                (f.id for f in db.facts_by_subject(nf.subject)
                 if f.statement == nf.statement and f.meeting_id == nf.source_meeting_id),
                None,
            )
            c = Contradiction(
                subject=nf.subject,
                explanation=verdict.get("explanation", ""),
                severity=verdict.get("severity", "trung bình"),
                fact_a_id=old.id, fact_b_id=new_id,
            )
            db.save_contradiction(c)
            db.set_fact_status(old.id, "đã thay thế")
            found.append(c)
    return found


# ---------------------------------------------------------------- forgotten decisions

def _find_fact_id(nf: KnowledgeFact) -> int | None:
    return next(
        (f.id for f in db.facts_by_subject(nf.subject)
         if f.statement == nf.statement and f.meeting_id == nf.source_meeting_id),
        None,
    )


def _forgotten_prompt(new: KnowledgeFact, old_subject: str, old_statement: str) -> str:
    return (
        "Một phát biểu MỚI và một phát biểu CŨ (từ cuộc họp TRƯỚC) cùng chủ đề. Phát biểu mới "
        "có phải là việc/ý tưởng ĐÃ TỪNG bị BÁC BỎ (rejected), hoặc ĐÃ NÊU RỒI BỊ BỎ QUÊN/chưa "
        "làm (forgotten) ở cuộc họp cũ, nay được NHẮC LẠI không?\n"
        f"CŨ (chủ đề '{old_subject}'): {old_statement}\n"
        f"MỚI (chủ đề '{new.subject}'): {new.statement}\n"
        "Chỉ trả 'rejected'/'forgotten' khi thực sự đúng; nếu chỉ là cập nhật/tiếp nối bình "
        "thường thì 'none'.\n"
        'Trả về DUY NHẤT JSON: {"resurfaced": true|false, '
        '"kind": "rejected"|"forgotten"|"none", "explanation": str}'
    )


def detect_forgotten_decisions(new_facts: list[KnowledgeFact]) -> list[dict]:
    """For each new decision/commitment, check earlier meetings for the same topic
    being rejected or raised-then-dropped, now resurfacing. Saves to db.resurfaced."""
    found: list[dict] = []
    all_facts = db.all_facts(limit=10000)
    for nf in new_facts:
        if nf.source_meeting_id is None or nf.type not in ("quyết định", "cam kết"):
            continue
        nm = db.get_meeting(nf.source_meeting_id)
        if not nm:
            continue
        nf_tokens = retrieve_mod._tokens(nf.subject)
        for f in all_facts:
            if f.meeting_id == nf.source_meeting_id:
                continue
            om = db.get_meeting(f.meeting_id)
            if not om or (om.date or "") > (nm.date or ""):   # must be from an earlier meeting
                continue
            if not (retrieve_mod._tokens(f.subject) & nf_tokens):
                continue
            if f.statement.strip() == nf.statement.strip():
                continue
            try:
                v = _chat_json(_forgotten_prompt(nf, f.subject, f.statement),
                               (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
            except ValueError:
                continue
            if not v.get("resurfaced") or v.get("kind") not in ("rejected", "forgotten"):
                continue
            new_id = _find_fact_id(nf)
            db.save_resurfaced(nf.subject, v["kind"], v.get("explanation", ""), f.id, new_id)
            found.append({"subject": nf.subject, "kind": v["kind"],
                          "explanation": v.get("explanation", "")})
            break  # one finding per new fact is enough
    return found


def scan_forgotten() -> list[dict]:
    """On-demand full rescan: rebuild the resurfaced table over all decision facts."""
    db.clear_resurfaced()
    models = [f.to_model() for f in db.all_facts(limit=10000)]   # chronological
    return detect_forgotten_decisions(models)


def resurfaced_view() -> list[dict]:
    """Resurfaced decisions enriched for the UI (citations + ≈timestamps)."""
    out = []
    for r in db.all_resurfaced():
        out.append({
            "subject": r.subject, "kind": r.kind, "explanation": r.explanation,
            "old": _fact_citation(r.old_fact_id),   # lần nêu/bác trước
            "new": _fact_citation(r.new_fact_id),   # lần nhắc lại
        })
    return out


# ---------------------------------------------------------------- ingest

def ingest(text: str | None = None, audio: bytes | None = None,
           date: str | None = None, title: str | None = None,
           language: str = "vi", filename: str = "meeting.wav",
           extract: bool = True, source_file: str | None = None,
           on_duplicate: str = "new") -> dict:
    """Full ingest pipeline. Accepts a transcript directly or audio/video bytes.

    For audio/video: transcode to mono-16k WAV (the STT endpoint only accepts WAV),
    split into chunks for long recordings, transcribe each, and join.

    Same-file handling (audio only, via audio_hash) by `on_duplicate`:
      "skip"      -> if already ingested, return the existing meeting untouched.
      "overwrite" -> delete the existing meeting, then ingest fresh.
      "new"       -> always create a separate meeting (default).
    Returns {meeting_id, report, facts, contradictions, skipped, duplicate_of}."""
    date = date or _dt.date.today().isoformat()
    duration_sec = None
    chunk_map = None
    ah = None
    if text is None:
        if not audio:
            raise ValueError("ingest needs text or audio")
        ah = db.audio_hash(audio)                       # hash RAW upload (same file -> same hash)
        existing = db.find_by_audio_hash(ah)
        if existing and on_duplicate == "skip":
            return {"meeting_id": existing.id, "report": existing.report(), "facts": [],
                    "contradictions": [], "skipped": True, "duplicate_of": existing.id}
        if existing and on_duplicate == "overwrite":
            db.delete_meeting(existing.id)

        import media
        chunks = media.audio_to_wav_chunks(
            audio, filename, chunk_sec=config.STT_CHUNK_SEC, do_extract=extract,
        )
        # Per chunk, correction order: STT (raw) -> LLM context-aware fix (primary)
        # -> regex cleanup (deterministic guarantee for known terms). Per-chunk so
        # each LLM correction call stays small/bounded.
        parts = []
        chunk_entries = []        # [{t0,c0,clen,dur}] for chunk-accurate ≈timestamps
        char_cursor = 0
        time_cursor = 0.0
        for c in chunks:
            d = media.wav_duration(c)
            t0 = time_cursor
            time_cursor += d
            t = transcribe.transcribe(c, filename="audio.wav", language=language)
            t = correct_terms(t)                  # layer chính: LLM hiểu ngữ cảnh
            t = transcribe.apply_corrections(t)   # layer sau: regex chuẩn hoá/đảm bảo
            if not t:
                continue
            if parts:
                char_cursor += 1                  # the "\n" join separator
            chunk_entries.append({"t0": round(t0, 2), "c0": char_cursor,
                                  "clen": len(t), "dur": round(d, 2)})
            char_cursor += len(t)
            parts.append(t)
        text = "\n".join(parts)
        duration_sec = int(time_cursor) or None
        chunk_map = json.dumps(chunk_entries) if chunk_entries else None
    if not text.strip():
        raise ValueError("empty transcript")

    report = analyze.analyze(text, date=date)
    if title:
        report.title = title

    # "new" must not collapse into an identical prior row -> force a separate row.
    salt = str(_dt.datetime.now().timestamp()) if on_duplicate == "new" else ""
    meeting_id = db.save_meeting(
        report, transcript=text, duration_sec=duration_sec, source_file=source_file,
        audio_hash_val=ah, dedup=(on_duplicate != "new"), dedup_salt=salt, chunk_map=chunk_map,
    )

    facts = extract_facts(report, text)
    for f in facts:
        f.source_meeting_id = meeting_id
    db.save_facts(meeting_id, facts)

    contradictions = detect_contradictions(facts)
    forgotten = detect_forgotten_decisions(facts)   # proactive: decisions resurfacing

    return {
        "meeting_id": meeting_id,
        "report": report,
        "facts": facts,
        "contradictions": contradictions,
        "forgotten": forgotten,
        "skipped": False,
        "duplicate_of": None,
    }


def reanalyze(meeting_id: int, transcript: str) -> dict:
    """Re-run analysis after a transcript edit: update transcript, regenerate the
    report + facts, and re-check contradictions. Keeps the meeting's title/date."""
    m = db.get_meeting(meeting_id)
    if not m:
        raise ValueError(f"meeting {meeting_id} not found")
    db.update_transcript(meeting_id, transcript)
    report = analyze.analyze(transcript, date=m.date)
    report.title = m.title
    report.full_transcript = transcript
    db.update_report(meeting_id, report)
    db.clear_facts(meeting_id)
    facts = extract_facts(report, transcript)
    for f in facts:
        f.source_meeting_id = meeting_id
    db.save_facts(meeting_id, facts)
    contradictions = detect_contradictions(facts)
    forgotten = detect_forgotten_decisions(facts)
    return {"meeting_id": meeting_id, "report": report, "facts": facts,
            "contradictions": contradictions, "forgotten": forgotten}


# ------------------------------------------------- timestamp + contradiction view

def estimate_timestamp(meeting, quote: str) -> str | None:
    """APPROXIMATE 'mm:ss' of where `quote` was said, for listen-back. STT returns no
    real timestamps, so we locate the quote's char index in the transcript and map it
    to time. If a chunk_map exists we map index -> the right audio chunk -> proportional
    within that chunk (much tighter); else fall back to whole-transcript proportional."""
    if not meeting or not quote:
        return None
    transcript = meeting.transcript or ""
    dur = meeting.duration_sec or 0
    if not transcript or dur <= 0:
        return None
    needle = quote.strip().lower()
    hay = transcript.lower()
    idx = hay.find(needle)
    if idx < 0 and len(needle) > 20:          # try a prefix if the full quote drifted
        idx = hay.find(needle[:20])
    if idx < 0:
        return None

    sec = None
    raw_map = getattr(meeting, "chunk_map", None)
    if raw_map:
        try:
            for ch in json.loads(raw_map):
                if ch["c0"] <= idx < ch["c0"] + max(ch["clen"], 1):
                    frac = (idx - ch["c0"]) / max(ch["clen"], 1)
                    sec = int(ch["t0"] + frac * ch["dur"])
                    break
        except Exception:  # noqa: BLE001 - bad/old map -> proportional fallback
            sec = None
    if sec is None:
        sec = int((idx / max(len(transcript), 1)) * dur)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _fact_citation(fact_id: int | None) -> dict | None:
    """Expand a fact id into {statement, quote, meeting_id, meeting_title, date, timestamp}."""
    if not fact_id:
        return None
    f = db.get_fact(fact_id)
    if not f:
        return None
    m = db.get_meeting(f.meeting_id)
    return {
        "statement": f.statement,
        "quote": f.quote or "",
        "meeting_id": f.meeting_id,
        "meeting_title": m.title if m else "",
        "date": m.date if m else "",
        "timestamp": estimate_timestamp(m, f.quote or f.statement),
    }


def contradiction_view() -> list[dict]:
    """All contradictions enriched for the UI: explanation + both sides' quotes,
    source meeting citations, and approximate listen-back timestamps."""
    out = []
    for c in db.all_contradictions():
        out.append({
            "subject": c.subject,
            "explanation": c.explanation,
            "severity": c.severity,
            "old": _fact_citation(c.fact_a_id),   # phát biểu cũ (bị thay thế)
            "new": _fact_citation(c.fact_b_id),   # phát biểu mới
        })
    return out


# ---------------------------------------------------------------- ask (recall Q&A)

def _ts_seconds(ts: str | None) -> int:
    if not ts:
        return 10 ** 9
    mm, ss = ts.split(":")
    return int(mm) * 60 + int(ss)


def _context_block(ctx: "retrieve_mod.RetrievedContext") -> str:
    """Decision-intelligence grounding: facts grouped by meeting and ordered by
    ≈timestamp so co-temporal evidence sits together; decisions are marked so the
    model can reason about a decision alongside the evidence said at the same time."""
    # resolve every meeting referenced by the retrieved facts (some may be outside ctx.meetings)
    mmap = {m.id: m for m in ctx.meetings}
    by_meeting: dict[int, list] = {}
    for f in ctx.facts:
        by_meeting.setdefault(f.meeting_id, []).append(f)
        if f.meeting_id not in mmap:
            mm = db.get_meeting(f.meeting_id)
            if mm:
                mmap[f.meeting_id] = mm

    meetings_sorted = sorted(mmap.values(), key=lambda x: (x.date or "", x.id or 0))
    lines = ["### Bằng chứng theo cuộc họp & mốc thời gian "
             "(các mục ⏱≈ gần nhau = nói cùng thời điểm → dùng để suy luận):"]
    for m in meetings_sorted:
        lines.append(f"\n[meeting_id={m.id}] {m.title} — {m.date}")
        if m.summary:
            lines.append(f"  Tóm tắt: {m.summary}")
        facts = by_meeting.get(m.id, [])
        facts = sorted(facts, key=lambda f: _ts_seconds(estimate_timestamp(m, f.quote or f.statement)))
        for f in facts:
            ts = estimate_timestamp(m, f.quote or f.statement)
            tflag = f" ⏱≈{ts}" if ts else ""
            dec = " [QUYẾT ĐỊNH]" if f.type == "quyết định" else ""
            stat = "" if f.status == "hiệu lực" else f" (TRẠNG THÁI:{f.status})"
            q = f' | trích: "{f.quote}"' if f.quote else ""
            lines.append(f"   -{tflag}{dec} ({f.type}) {f.subject}: {f.statement}{stat}{q}")
    return "\n".join(lines)


def _ask_prompt(question: str, context: str) -> str:
    return (
        "Bạn là 'bộ não cuộc họp' của tổ chức. Trả lời câu hỏi CHỈ dựa trên ngữ cảnh bên dưới. "
        "Quy tắc suy luận (Decision Intelligence):\n"
        "- Khi đánh giá một QUYẾT ĐỊNH, hãy dựa vào các bằng chứng có ⏱≈ GẦN NHAU trong cùng "
        "cuộc họp (nói cùng thời điểm) như là lý do/bối cảnh của quyết định đó — nêu căn cứ.\n"
        "- Nếu một chủ đề/quyết định thay đổi qua thời gian, trình bày theo DÒNG THỜI GIAN và "
        "ưu tiên trạng thái MỚI NHẤT (theo ngày họp + ⏱); nói rõ nó thay cho cái cũ.\n"
        "- Mỗi ý phải kèm trích nguồn (meeting_id) trong 'citations'; khi có thể, trích câu gốc.\n"
        "- Nếu ngữ cảnh KHÔNG có thông tin, nói rõ 'Chưa từng được đề cập trong các cuộc họp.' "
        "Tuyệt đối không bịa.\n"
        'Trả về DUY NHẤT JSON: {"answer": str, "citations": '
        '[{"meeting_id": int, "quote": str}]}\n\n'
        f"NGỮ CẢNH:\n{context}\n\nCÂU HỎI: {question}"
    )


def ask(question: str, limit: int = 50) -> Answer:
    """Historical Recall Q&A across the full meeting memory, with citations."""
    ctx = retrieve_mod.retrieve(question, limit=limit)
    if ctx.is_empty():
        return Answer(text="Chưa có cuộc họp nào được ghi nhớ.", citations=[])

    try:
        data = _chat_json(
            _ask_prompt(question, _context_block(ctx)),
            (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL),
        )
    except ValueError:
        return Answer(text="Xin lỗi, không tạo được câu trả lời lúc này.", citations=[])

    # enrich citations with meeting title/date + approximate listen-back timestamp
    citations: list[Citation] = []
    for c in data.get("citations", []):
        mid = c.get("meeting_id")
        m = db.get_meeting(mid) if mid else None
        quote = c.get("quote", "")
        citations.append(Citation(
            meeting_id=mid,
            meeting_title=m.title if m else "",
            date=m.date if m else "",
            quote=quote,
            timestamp=estimate_timestamp(m, quote) if m else None,
        ))
    return Answer(text=data.get("answer", ""), citations=citations)


# ---------------------------------------------------------------- digest

def _digest_prompt(context: str, scope_label: str) -> str:
    return (
        f"Bạn là chánh văn phòng. Viết BẢN TÓM TẮT ĐIỀU HÀNH cho lãnh đạo ({scope_label}), "
        "tổng hợp từ nhiều cuộc họp bên dưới: tình hình chung, quyết định lớn, rủi ro, việc còn treo.\n"
        "QUY TẮC VỀ 'risks' (rất quan trọng):\n"
        "- CHỈ đưa rủi ro/blocker THỰC SỰ trọng yếu (ảnh hưởng tiến độ, ngân sách, pháp lý, "
        "chất lượng, nhân sự, bảo mật...).\n"
        "- Ưu tiên dựa trên mục 'Rủi ro đã ghi nhận' và 'Mâu thuẫn' trong dữ liệu; KHÔNG bịa "
        "rủi ro không có trong dữ liệu.\n"
        "- TUYỆT ĐỐI KHÔNG coi câu nói đùa, nói vui, cường điệu, giả định bâng quơ hay nhận xét "
        "xã giao là rủi ro.\n"
        "- KHÔNG thổi phồng mức độ. Nếu không có rủi ro rõ ràng, trả mảng RỖNG [].\n"
        'Trả về DUY NHẤT JSON: {"summary": str, "key_points": [str], '
        '"decisions": [str], "risks": [str]}\n\n'
        f"DỮ LIỆU:\n{context}"
    )


def digest(scope: str = "all") -> MeetingReport:
    """Executive digest across meetings. Returns a MeetingReport so report.py can
    render it to docx/pdf unchanged (open actions become its action_items)."""
    import datetime as _d
    meetings = db.list_meetings(limit=10000)
    open_actions = [a for a in db.all_actions() if a.status != "xong"]
    contras = db.all_contradictions()

    parts = ["### Cuộc họp:"]
    risk_lines = []
    for m in meetings:
        parts.append(f"- {m.title} ({m.date}): {m.summary}")
        try:
            for r in m.report().risks:        # rủi ro ĐÃ trích cho từng cuộc họp
                risk_lines.append(f"- ({m.title}) {r}")
        except Exception:  # noqa: BLE001 - bad report_json -> skip its risks
            pass
    parts.append("\n### Rủi ro đã ghi nhận (chỉ tổng hợp từ đây, đừng bịa thêm):")
    parts.extend(risk_lines or ["- (không có)"])
    parts.append("\n### Việc còn mở:")
    for a in open_actions:
        parts.append(f"- {a.task} | {a.owner or '-'} | hạn {a.deadline or '-'} | {a.status}")
    parts.append("\n### Mâu thuẫn:")
    for c in contras:
        parts.append(f"- [{c.severity}] {c.subject}: {c.explanation}")
    context = "\n".join(parts)

    try:
        data = _chat_json(_digest_prompt(context, scope),
                          (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
    except ValueError:
        data = {"summary": "Không tạo được digest.", "key_points": [], "decisions": [], "risks": []}

    from models import Decision, ActionItem
    return MeetingReport(
        title=f"Executive Digest ({scope})",
        date=_d.date.today().isoformat(),
        summary=data.get("summary", ""),
        key_points=data.get("key_points", []),
        decisions=[Decision(text=d) for d in data.get("decisions", [])],
        action_items=[
            ActionItem(task=a.task, owner=a.owner, deadline=a.deadline,
                       priority=a.priority or "trung bình", status=a.status)
            for a in open_actions
        ],
        risks=data.get("risks", []) + [f"[Mâu thuẫn] {c.subject}: {c.explanation}" for c in contras],
        full_transcript="",
    )


# ---------------------------------------------------------------- follow_up

def _followup_prompt(action_task: str, owner: str, deadline: str, later_context: str) -> str:
    return (
        "Một việc (action item) được giao ở cuộc họp trước. Dựa trên nội dung các cuộc họp "
        "DIỄN RA SAU ĐÓ bên dưới, hãy đánh giá trạng thái hiện tại của việc này.\n"
        f"Việc: {action_task}\nNgười phụ trách: {owner or '-'}\nHạn: {deadline or '-'}\n\n"
        f"Các cuộc họp sau đó:\n{later_context}\n\n"
        'Trả về DUY NHẤT JSON: {"status": "mở"|"đang làm"|"xong"|"quá hạn"|"treo", '
        '"note": str, "related_meeting_id": int|null}'
    )


def follow_up() -> list[dict]:
    """Re-check each not-done action against meetings that happened AFTER it, update
    its status, and record where it was re-mentioned (action_links)."""
    meetings = db.list_meetings(limit=10000)
    by_id = {m.id: m for m in meetings}
    results: list[dict] = []

    for a in db.all_actions():
        if a.status == "xong":
            continue
        src = by_id.get(a.meeting_id)
        src_date = src.date if src else ""
        later = [m for m in meetings
                 if (m.id != a.meeting_id) and ((m.date or "") >= (src_date or ""))]
        later = [m for m in later if m.id != a.meeting_id]
        if not later:
            continue
        later_ctx = "\n".join(f"[meeting_id={m.id}] {m.title} ({m.date}): {m.summary}" for m in later)
        try:
            v = _chat_json(_followup_prompt(a.task, a.owner or "", a.deadline or "", later_ctx),
                           (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
        except ValueError:
            continue
        new_status = v.get("status")
        if new_status and new_status != a.status:
            db.update_action_status(a.id, new_status)
        rel = v.get("related_meeting_id")
        if rel:
            db.add_action_link(a.id, rel, v.get("note", ""))
        results.append({"action_id": a.id, "task": a.task, "status": new_status or a.status,
                        "note": v.get("note", "")})
    return results
