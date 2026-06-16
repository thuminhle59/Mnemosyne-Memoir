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
import mailer
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

def _effective_glossary(owner_id: str | None = None) -> str:
    """Default glossary + org/team terms taught via the training guide (db)."""
    terms = [config.STT_GLOSSARY]
    try:
        extra = db.glossary_terms(owner_id=owner_id)
        if extra:
            terms.append(", ".join(extra))
    except Exception:  # noqa: BLE001 - DB not ready
        pass
    return ", ".join(t for t in terms if t)


def _correct_prompt(text: str, owner_id: str | None = None) -> str:
    return (
        "Dưới đây là transcript do nhận dạng giọng nói tạo ra, có thể nghe nhầm DANH TỪ RIÊNG.\n"
        f"Glossary tên đúng (CHỈ là gợi ý, có thể KHÔNG xuất hiện trong audio): {_effective_glossary(owner_id=owner_id)}\n"
        "Nhiệm vụ: CHỈ sửa những danh từ riêng bị nghe nhầm cho khớp glossary KHI NGỮ CẢNH "
        "cho thấy đúng là nó. Nếu transcript nói về chủ đề khác và không liên quan glossary, "
        "phải giữ nguyên tên riêng đã nghe được như Nova, Merchant, Portal nếu chúng đã hợp lý. "
        "GIỮ NGUYÊN, KHÔNG thêm thắt. Tuyệt đối KHÔNG diễn giải lại, KHÔNG tóm tắt, KHÔNG đổi "
        "từ thường — giữ nguyên 100% nội dung, chỉ thay đúng các tên bị sai. "
        f"{analyze.PRESERVE_ENGLISH_TERMS_RULE}\n"
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


def learn_glossary(guide_text: str, owner_id: str | None = None) -> list[str]:
    """Extract terms from a guide and persist them; returns the terms saved."""
    terms = extract_glossary_terms(guide_text)
    for t in terms:
        db.add_glossary(t, owner_id=owner_id)
    return terms


def _is_known_correction_source(term: str, owner_id: str | None = None) -> bool:
    for pattern, _repl in [*config.STT_NORMALIZE, *config.STT_TERM_FIXES]:
        if re.search(pattern, term, flags=re.IGNORECASE):
            return True
    try:
        for wrong, _target in db.glossary_fixes(owner_id=owner_id):
            pattern = r"\b" + re.escape(wrong).replace(r"\ ", r"[\s-]?") + r"\b"
            if re.search(pattern, term, flags=re.IGNORECASE):
                return True
    except Exception:  # noqa: BLE001 - DB not ready
        pass
    return False


def _protected_proper_nouns(text: str, owner_id: str | None = None) -> set[str]:
    """Proper nouns already present in STT output that are not known misspellings.

    The LLM correction layer may use glossary hints, but it must not replace a
    real project/customer name such as "Nova" with a glossary term like
    "OpenClaw" just because the glossary contains it.
    """
    terms = set()
    for term in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)*\b", text or ""):
        if len(term) < 3:
            continue
        if term.isupper() and len(term) <= 3:
            continue
        if _is_known_correction_source(term, owner_id=owner_id):
            continue
        terms.add(term)
    return terms


def _keeps_protected_proper_nouns(original: str, corrected: str, owner_id: str | None = None) -> bool:
    output = corrected.lower()
    return all(term.lower() in output for term in _protected_proper_nouns(original, owner_id=owner_id))


def correct_terms(text: str, owner_id: str | None = None) -> str:
    """Context-aware proper-noun fix via LLM. Safe on unknown topics (won't force
    glossary terms). Guardrailed: if the model returns nothing or rewrites too much
    (length drifts far from the original), the original is kept."""
    if not config.STT_LLM_CORRECT or not text.strip():
        return text
    try:
        data = _chat_json(_correct_prompt(text, owner_id=owner_id),
                          (config.STT_CORRECT_MODEL, config.REASONING_FALLBACK_MODEL))
    except ValueError:
        return text
    out = (data.get("corrected") or "").strip()
    if not out:
        return text
    ratio = len(out) / max(len(text), 1)
    if ratio < 0.6 or ratio > 1.6:   # over-edit / truncation guard -> keep original
        return text
    if not _keeps_protected_proper_nouns(text, out, owner_id=owner_id):
        return text
    return out


# ---------------------------------------------------------------- extract_facts

def _facts_prompt(report: MeetingReport, transcript: str) -> str:
    return (
        "Bạn là trợ lý phân tích cuộc họp. Từ biên bản và transcript bên dưới, hãy TRÍCH các "
        "'fact nguyên tử' để LƯU VÀO BỘ NHỚ TỔ CHỨC, dùng đối chiếu xuyên NHIỀU cuộc họp.\n"
        "Loại fact: 'quyết định' (chốt làm/không làm việc gì), 'cam kết' (ai đó nhận một việc, "
        "có thể kèm hạn), 'số liệu' (con số/chỉ số/ngày tháng cụ thể), 'fact' (sự kiện/trạng thái "
        "khách quan), 'giả định', 'rủi ro'.\n"
        "QUY TẮC CHẤT LƯỢNG (BẮT BUỘC — quyết định độ chính xác khi đối chiếu về sau):\n"
        f"0. {analyze.PRESERVE_ENGLISH_TERMS_RULE}\n"
        "1. SUBJECT: cụm danh từ NGẮN, CHUẨN HOÁ, và NHẤT QUÁN cho cùng một chủ đề — DÙNG LẠI "
        "đúng MỘT cách gọi cho cùng một việc (vd luôn dùng 'ngày go-live', đừng lúc 'ngày deploy' "
        "lúc 'ngày canary' lúc 'quyết định go canary'). KHÔNG nhét động từ/kết luận vào subject.\n"
        "2. STATEMENT: phải TỰ ĐỦ NGHĨA và chứa GIÁ TRỊ TUYỆT ĐỐI (ngày/số/kết luận cụ thể). "
        "KHÔNG tham chiếu 'như trên'/'phát biểu trước'. KHÔNG tạo fact dạng SỐ LIỆU PHÁI SINH hay "
        "so sánh tương đối (vd ĐỪNG ghi 'trễ 8 ngày so với baseline'; hãy ghi giá trị thật: "
        "'UAT hoàn tất ngày 28/5, kế hoạch ban đầu là 20/5').\n"
        "3. QUOTE: câu GỐC NGUYÊN VĂN trích từ transcript (để định vị thời điểm); nếu không có "
        "câu gốc rõ ràng thì để null — KHÔNG bịa quote.\n"
        "4. Mỗi claim chỉ MỘT fact; GỘP các câu nhắc lại cùng nội dung. BỎ QUA chào hỏi, nói đùa, "
        "câu xã giao và thủ tục vụn vặt không có giá trị ghi nhớ.\n"
        "5. ĐƯỢC trích fact hoặc quyết định từ phần Tóm tắt nếu đó là kết luận/trạng thái thật của cuộc họp "
        "và không có câu gốc nguyên văn rõ hơn trong transcript. Khi dùng claim từ Tóm tắt, quote có thể là null.\n"
        "6. KHÔNG trích META-BÌNH LUẬN của biên bản về chính nó (vd 'Quyết định ghi nhận:...', "
        "'Ghi nhận có mâu thuẫn...', 'đánh dấu conflict để họp sau xử lý') thành fact. Hãy trích "
        "NỘI DUNG GỐC bên dưới (giá trị/quyết định thực), KHÔNG trích câu nói rằng 'có mâu thuẫn'. "
        "Subject KHÔNG được là 'conflict...'/'ghi nhận...'.\n"
        "Trả về DUY NHẤT JSON hợp lệ, KHÔNG markdown, KHÔNG giải thích.\n"
        f"Schema:\n{_FACT_SCHEMA}\n\n"
        f"Tóm tắt: {report.summary}\n"
        f"Transcript:\n{transcript}"
    )


def _dedupe_facts(facts: list[KnowledgeFact]) -> list[KnowledgeFact]:
    """Drop within-meeting duplicates (same subject+statement, case/space-insensitive),
    keeping the first occurrence — fewer redundant facts = less downstream noise."""
    seen: set[tuple] = set()
    out: list[KnowledgeFact] = []
    for f in facts:
        key = (" ".join(f.subject.lower().split()), " ".join(f.statement.lower().split()))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def extract_facts(report: MeetingReport, transcript: str) -> list[KnowledgeFact]:
    """One LLM pass → atomic KnowledgeFact[], deduped. Best-effort: returns [] on failure
    so a meeting still ingests (report is the source of truth) even if extraction fails."""
    try:
        data = _chat_json(
            _facts_prompt(report, transcript),
            (config.EXTRACT_MODEL, config.EXTRACT_FALLBACK_MODEL),
        )
    except ValueError:
        return []
    try:
        return _dedupe_facts(FactList.model_validate(data).facts)
    except Exception:  # noqa: BLE001 - shape drift -> no facts rather than crash
        return []


# ---------------------------------------------------------------- contradictions

# Only concrete claims trigger contradiction detection; speculative types
# (assumptions, risks) are noisy and routinely flag false conflicts.
_CONCRETE_TYPES = ("quyết định", "fact", "số liệu", "cam kết")
# Cap candidates per new fact so a heavily-discussed subject can't blow up one prompt.
_MAX_CANDIDATES = 40

_CONTRA_RULES = (
    "Coi là mâu thuẫn KHI cùng nói về MỘT việc/chủ đề mà giá trị/kết luận nghịch nhau "
    "(không thể cùng đúng). KHÔNG coi là mâu thuẫn nếu: (a) là hai việc khác nhau; "
    "(b) phát biểu mới chỉ CẬP NHẬT/CHI TIẾT HOÁ bình thường; (c) hai câu thực chất mô tả "
    "CÙNG MỘT thực tế nhưng diễn đạt khác, hoặc một câu là SỐ LIỆU PHÁI SINH/tính lại từ "
    "câu kia (ví dụ 'trễ đến ngày 28/5' và 'trễ 8 ngày so với 20/5' là NHẤT QUÁN). "
    "Khi còn phân vân, KHÔNG coi là mâu thuẫn."
)

_PILOT_SELECTION_TOKENS = {
    "chon", "select", "selection", "shortlist", "lua", "danh", "sach", "onboard", "onboarding"
}


def _fact_tokens(fact) -> set[str]:
    return retrieve_mod._tokens(f"{getattr(fact, 'subject', '')} {getattr(fact, 'statement', '')}")


def _plain_text(value: str) -> str:
    return retrieve_mod._strip_diacritics(value or "").lower()


def _same_meeting_source(a, b) -> bool:
    if not a or not b or a.id == b.id:
        return False
    if a.audio_hash and b.audio_hash and a.audio_hash == b.audio_hash:
        return True
    if a.content_hash and b.content_hash and a.content_hash == b.content_hash:
        return True
    if a.source_file and b.source_file and a.source_file == b.source_file and (a.date or "") == (b.date or ""):
        return True
    return False


def _same_contradiction_target(old, new: KnowledgeFact) -> bool:
    """Cheap guard before the LLM: dates for selecting pilot merchants and dates for
    running the pilot are different milestones, even if their subjects share words."""
    old_tokens = _fact_tokens(old)
    new_tokens = _fact_tokens(new)
    old_selection = bool(old_tokens & _PILOT_SELECTION_TOKENS)
    new_selection = bool(new_tokens & _PILOT_SELECTION_TOKENS)
    if "pilot" in old_tokens and "pilot" in new_tokens and old_selection != new_selection:
        return False
    return True


def _verdict_is_actual_conflict(verdict: dict) -> bool:
    explanation = _plain_text(str(verdict.get("explanation", "")))
    if "khong mau thuan" in explanation or "khong phai mau thuan" in explanation:
        return False
    if "nhat quan" in explanation:
        return False
    return True


def _batch_contra_prompt(new: KnowledgeFact, candidates: list, new_when: str = "") -> str:
    """One prompt comparing a new fact against ALL its same-subject candidates at once;
    the model returns the indices that conflict (collapses N×M pairwise calls into N)."""
    new_ctx = f" [{new_when}]" if new_when else ""
    lines = []
    for i, (old, when) in enumerate(candidates):
        ctx = f" [{when}]" if when else ""
        lines.append(f"  {i}. (chủ đề '{old.subject}'){ctx}: {old.statement}")
    listing = "\n".join(lines)
    return (
        f"Phát biểu MỚI{new_ctx} (chủ đề '{new.subject}'): {new.statement}\n\n"
        "Dưới đây là các phát biểu CŨ cùng chủ đề từ các cuộc họp trước (đánh số). "
        "Hãy chỉ ra những phát biểu cũ MÂU THUẪN với phát biểu mới.\n"
        f"{_CONTRA_RULES}\n\n"
        f"DANH SÁCH CŨ:\n{listing}\n\n"
        "Với mỗi mâu thuẫn, 'explanation' nêu rõ sự THAY ĐỔI theo thời gian: phát biểu CŨ (từ "
        "cuộc họp TRƯỚC) nêu điều gì, phát biểu MỚI (cuộc họp sau, tức phát biểu gốc ở trên) "
        "thay đổi thành gì — viết 1 câu theo dạng 'Trước: X → Nay: Y'. "
        "'severity' theo mức ảnh hưởng. Nếu không có cái nào mâu thuẫn, trả về danh sách rỗng.\n"
        'Trả về DUY NHẤT JSON: {"conflicts": [{"index": int, "explanation": str, '
        '"severity": "cao"|"trung bình"|"thấp"}]}'
    )


def _when(meeting) -> str:
    """Short 'title — date' label for a meeting, for grounding LLM verdicts."""
    if not meeting:
        return ""
    return " — ".join(p for p in (meeting.title, meeting.date) if p)


def detect_contradictions(new_facts: list[KnowledgeFact]) -> list[Contradiction]:
    """For each new fact, compare with EARLIER active facts of the same subject.
    On conflict: record a Contradiction, mark the older fact 'đã thay thế', and
    surface it (caller shows a proactive warning). Runs at ingest time."""
    found: list[Contradiction] = []
    all_active = [f for f in db.all_facts(limit=10000) if f.status == "hiệu lực"]
    for nf in new_facts:
        if nf.source_meeting_id is None or nf.type not in _CONCRETE_TYPES:
            continue
        new_when = _when(db.get_meeting(nf.source_meeting_id))
        # Candidates = earlier active facts whose subject SHARES a token with this one.
        # Exact-subject matching misses conflicts when the model words the same topic
        # differently across meetings ("ngày launch" vs "ngày ra mắt"); the LLM verdict
        # below filters out coincidental token overlaps.
        nf_tokens = retrieve_mod._tokens(nf.subject)
        new_meeting = db.get_meeting(nf.source_meeting_id)
        new_date = (new_meeting.date or "") if new_meeting else ""
        candidates = [
            f for f in all_active
            if f.meeting_id != nf.source_meeting_id
            and (retrieve_mod._tokens(f.subject) & nf_tokens)
            and _same_contradiction_target(f, nf)
            and not _same_meeting_source(db.get_meeting(f.meeting_id), new_meeting)
            and f.statement.strip() != nf.statement.strip()   # identical restatement is no conflict
            and ((db.get_meeting(f.meeting_id).date or "") if db.get_meeting(f.meeting_id) else "") <= new_date
        ]
        if not candidates:
            continue
        # most-recent-first, capped, so one prompt stays bounded on busy subjects
        candidates.sort(key=lambda f: ((db.get_meeting(f.meeting_id).date or "")
                                       if db.get_meeting(f.meeting_id) else "", f.id or 0),
                        reverse=True)
        candidates = candidates[:_MAX_CANDIDATES]
        labeled = [(f, _when(db.get_meeting(f.meeting_id))) for f in candidates]

        # ONE batched call: ask which candidates conflict (collapses N×M -> N calls).
        try:
            data = _chat_json(_batch_contra_prompt(nf, labeled, new_when=new_when),
                              (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
        except ValueError:
            continue
        conflicts: list[tuple] = []   # (old_fact, verdict)
        for item in data.get("conflicts", []):
            idx = item.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
                continue   # ignore hallucinated/out-of-range indices
            if not _verdict_is_actual_conflict(item):
                continue
            conflicts.append((candidates[idx], item))
        if not conflicts:
            continue
        # A new value routinely conflicts with several prior values of the same subject;
        # supersede ALL of them but surface ONE row (most severe; tie -> most recent old).
        for old, _v in conflicts:
            db.set_fact_status(old.id, "đã thay thế")
        _sev_rank = {"cao": 3, "trung bình": 2, "thấp": 1}
        old, verdict = max(
            conflicts,
            key=lambda cv: (_sev_rank.get(cv[1].get("severity"), 2),
                            (db.get_meeting(cv[0].meeting_id).date or "") if db.get_meeting(cv[0].meeting_id) else ""),
        )
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
        found.append(c)
    return found


def redetect_all_contradictions() -> dict:
    """Wipe existing contradictions, reset replaced facts, then re-run detection
    chronologically across all meetings so temporal ordering is always correct."""
    cleared = db.clear_all_contradictions()
    # Process meetings oldest-first so each pass only sees truly earlier facts.
    meetings = sorted(db.list_meetings(limit=10000), key=lambda m: (m.date or "", m.id or 0))
    total_found = 0
    for m in meetings:
        facts = [f.to_model() for f in db.facts_of_meeting(m.id)
                 if f.type in _CONCRETE_TYPES]
        if not facts:
            continue
        found = detect_contradictions(facts)
        total_found += len(found)
    return {"cleared": cleared, "meetings_processed": len(meetings), "found": total_found}


# ---------------------------------------------------------------- forgotten decisions

def _find_fact_id(nf: KnowledgeFact) -> int | None:
    return next(
        (f.id for f in db.facts_by_subject(nf.subject)
         if f.statement == nf.statement and f.meeting_id == nf.source_meeting_id),
        None,
    )


def _batch_forgotten_prompt(new: KnowledgeFact, candidates: list) -> str:
    """One prompt comparing a new decision against ALL earlier same-subject statements;
    the model picks the single strongest 'rejected/forgotten then resurfaced' match."""
    lines = []
    for i, (old, when) in enumerate(candidates):
        ctx = f" [{when}]" if when else ""
        lines.append(f"  {i}. (chủ đề '{old.subject}'){ctx}: {old.statement}")
    listing = "\n".join(lines)
    return (
        f"Phát biểu MỚI (quyết định/cam kết) (chủ đề '{new.subject}'): {new.statement}\n\n"
        "Dưới đây là các phát biểu CŨ cùng chủ đề từ các cuộc họp TRƯỚC (đánh số).\n"
        "Phát biểu mới có phải là việc/ý tưởng mà ở cuộc họp cũ ĐÃ bị BÁC BỎ (rejected) hoặc "
        "ĐÃ NÊU RỒI BỊ BỎ QUÊN/không làm (forgotten), nay BẤT NGỜ được NHẮC/ĐỀ XUẤT LẠI không?\n"
        "RẤT QUAN TRỌNG — chỉ là 'rejected'/'forgotten' khi phát biểu CŨ cho thấy rõ việc đó từng "
        "bị TỪ CHỐI hoặc BỎ DỞ. Nếu phát biểu mới chỉ NHẮC LẠI / TÁI XÁC NHẬN / TIẾP NỐI một "
        "phương án ĐÃ ĐƯỢC THỐNG NHẤT và vẫn đang đi đúng hướng (kể cả khi diễn đạt khác hay chi "
        "tiết hơn), thì đó là tính NHẤT QUÁN bình thường → kind='none', resurfaced=false. "
        "Khi còn phân vân → 'none'.\n\n"
        f"DANH SÁCH CŨ:\n{listing}\n\n"
        "Nếu CÓ, chọn MỘT phát biểu cũ thể hiện rõ nhất việc bị bác/bỏ dở.\n"
        'Trả về DUY NHẤT JSON: {"resurfaced": true|false, "index": int|null, '
        '"kind": "rejected"|"forgotten"|"none", "explanation": str}'
    )


def detect_forgotten_decisions(new_facts: list[KnowledgeFact]) -> list[dict]:
    """For each new decision/commitment, check earlier meetings for the same topic
    being rejected or raised-then-dropped, now resurfacing. Saves to db.resurfaced.
    One batched LLM call per new fact (all earlier same-subject statements at once)."""
    found: list[dict] = []
    all_facts = db.all_facts(limit=10000)
    for nf in new_facts:
        if nf.source_meeting_id is None or nf.type not in ("quyết định", "cam kết"):
            continue
        nm = db.get_meeting(nf.source_meeting_id)
        if not nm:
            continue
        nf_tokens = retrieve_mod._tokens(nf.subject)
        candidates = []
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
            candidates.append((f, _when(om)))
        if not candidates:
            continue
        candidates = candidates[:_MAX_CANDIDATES]
        try:
            v = _chat_json(_batch_forgotten_prompt(nf, candidates),
                           (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
        except ValueError:
            continue
        if not v.get("resurfaced") or v.get("kind") not in ("rejected", "forgotten"):
            continue
        idx = v.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
            continue   # need a valid pointer to the earlier statement
        old = candidates[idx][0]
        new_id = _find_fact_id(nf)
        db.save_resurfaced(nf.subject, v["kind"], v.get("explanation", ""), old.id, new_id)
        found.append({"subject": nf.subject, "kind": v["kind"],
                      "explanation": v.get("explanation", "")})
    return found


def scan_forgotten() -> list[dict]:
    """On-demand full rescan: rebuild the resurfaced table over all decision facts."""
    db.clear_resurfaced()
    models = [f.to_model() for f in db.all_facts(limit=10000)]   # chronological
    return detect_forgotten_decisions(models)


def resurfaced_view(owner_id: str | None = None) -> list[dict]:
    """Resurfaced decisions enriched for the UI (citations + ≈timestamps)."""
    out = []
    for r in db.all_resurfaced():
        out.append({
            "subject": r.subject, "kind": r.kind, "explanation": r.explanation,
            "old": _fact_citation(r.old_fact_id, owner_id=owner_id),   # lần nêu/bác trước
            "new": _fact_citation(r.new_fact_id, owner_id=owner_id),   # lần nhắc lại
        })
    return out


# ---------------------------------------------------------------- ingest

def ingest(text: str | None = None, audio: bytes | None = None,
           date: str | None = None, title: str | None = None,
           language: str = "vi", filename: str = "meeting.wav",
           extract: bool = True, source_file: str | None = None,
           on_duplicate: str = "new", owner_id: str | None = None) -> dict:
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
    duplicate_of = None
    cloned_facts: list[KnowledgeFact] | None = None
    if text is None:
        if not audio:
            raise ValueError("ingest needs text or audio")
        ah = db.audio_hash(audio)                       # hash RAW upload (same file -> same hash)
        existing = db.find_by_audio_hash(ah, owner_id=owner_id)
        if existing and on_duplicate == "skip":
            return {"meeting_id": existing.id, "report": existing.report(), "facts": [],
                    "contradictions": [], "skipped": True, "duplicate_of": existing.id}
        if existing and on_duplicate == "overwrite":
            db.delete_meeting(existing.id, owner_id=owner_id)
            existing = None
        if existing and on_duplicate == "new":
            duplicate_of = existing.id
            report = existing.report()
            if date:
                report.date = date
            if title:
                report.title = title
            text = existing.transcript or report.full_transcript
            report.full_transcript = text
            duration_sec = existing.duration_sec
            chunk_map = existing.chunk_map
            cloned_facts = [
                f.to_model().model_copy(update={"source_meeting_id": None})
                for f in db.facts_of_meeting(existing.id)
            ]
        else:
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
                t = correct_terms(t, owner_id=owner_id) if owner_id is not None else correct_terms(t)
                t = (
                    transcribe.apply_corrections(t, owner_id=owner_id)
                    if owner_id is not None
                    else transcribe.apply_corrections(t)
                )
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

    if cloned_facts is None:
        report = analyze.analyze(text, date=date)
        if title:
            report.title = title
        report = _apply_glossary_to_report(report, owner_id=owner_id)

    # "new" must not collapse into an identical prior row -> force a separate row.
    salt = str(_dt.datetime.now().timestamp()) if on_duplicate == "new" else ""
    meeting_id = db.save_meeting(
        report, transcript=text, duration_sec=duration_sec, source_file=source_file,
        audio_hash_val=ah, dedup=(on_duplicate != "new"), dedup_salt=salt, chunk_map=chunk_map,
        owner_id=owner_id,
    )

    facts = cloned_facts if cloned_facts is not None else [_apply_glossary_to_fact(f, owner_id=owner_id) for f in extract_facts(report, text)]
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
        "duplicate_of": duplicate_of,
    }


def _apply_glossary_text(value: str | None, owner_id: str | None = None) -> str | None:
    if value is None:
        return None
    if owner_id is None:
        return transcribe.apply_corrections(value)
    return transcribe.apply_corrections(value, owner_id=owner_id)


def _apply_glossary_to_report(report: MeetingReport, owner_id: str | None = None) -> MeetingReport:
    """Apply deterministic glossary mappings to every user-visible analysis field."""
    brief = report.summary_brief
    return report.model_copy(update={
        "title": _apply_glossary_text(report.title, owner_id=owner_id) or report.title,
        "summary": _apply_glossary_text(report.summary, owner_id=owner_id) or report.summary,
        "summary_brief": brief.model_copy(update={
            "context": _apply_glossary_text(brief.context, owner_id=owner_id),
            "decisions": [_apply_glossary_text(item, owner_id=owner_id) or item for item in brief.decisions],
            "risk": _apply_glossary_text(brief.risk, owner_id=owner_id),
            "next_step": _apply_glossary_text(brief.next_step, owner_id=owner_id),
        }),
        "key_points": [_apply_glossary_text(item, owner_id=owner_id) or item for item in report.key_points],
        "decisions": [
            d.model_copy(update={
                "text": _apply_glossary_text(d.text, owner_id=owner_id) or d.text,
                "quote": _apply_glossary_text(d.quote, owner_id=owner_id),
            })
            for d in report.decisions
        ],
        "action_items": [
            a.model_copy(update={
                "task": _apply_glossary_text(a.task, owner_id=owner_id) or a.task,
                "owner": _apply_glossary_text(a.owner, owner_id=owner_id),
                "deadline": _apply_glossary_text(a.deadline, owner_id=owner_id),
                "quote": _apply_glossary_text(a.quote, owner_id=owner_id),
            })
            for a in report.action_items
        ],
        "risks": [_apply_glossary_text(item, owner_id=owner_id) or item for item in report.risks],
        "open_questions": [_apply_glossary_text(item, owner_id=owner_id) or item for item in report.open_questions],
        "next_meeting": _apply_glossary_text(report.next_meeting, owner_id=owner_id),
        "full_transcript": _apply_glossary_text(report.full_transcript, owner_id=owner_id) or report.full_transcript,
    })


def _apply_glossary_to_fact(fact: KnowledgeFact, owner_id: str | None = None) -> KnowledgeFact:
    return fact.model_copy(update={
        "subject": _apply_glossary_text(fact.subject, owner_id=owner_id) or fact.subject,
        "statement": _apply_glossary_text(fact.statement, owner_id=owner_id) or fact.statement,
        "quote": _apply_glossary_text(fact.quote, owner_id=owner_id),
    })


def reanalyze(meeting_id: int, transcript: str, owner_id: str | None = None) -> dict:
    """Re-run analysis after a transcript edit: update transcript, regenerate the
    report + facts, and re-check contradictions. Keeps the meeting's title/date."""
    m = db.get_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.get_meeting(meeting_id)
    if not m:
        raise ValueError(f"meeting {meeting_id} not found")
    db.update_transcript(meeting_id, transcript)
    report = analyze.analyze(transcript, date=m.date)
    report.title = m.title
    report.full_transcript = transcript
    report = _apply_glossary_to_report(report, owner_id=owner_id)
    if owner_id is not None:
        db.update_report(meeting_id, report, owner_id=owner_id)
    else:
        db.update_report(meeting_id, report)
    db.clear_facts(meeting_id)
    facts = [_apply_glossary_to_fact(f, owner_id=owner_id) for f in extract_facts(report, transcript)]
    for f in facts:
        f.source_meeting_id = meeting_id
    db.save_facts(meeting_id, facts)
    contradictions = detect_contradictions(facts)
    forgotten = detect_forgotten_decisions(facts)
    return {"meeting_id": meeting_id, "report": report, "facts": facts,
            "contradictions": contradictions, "forgotten": forgotten}


def apply_glossary_to_meeting(meeting_id: int, owner_id: str | None = None) -> dict:
    """Apply current glossary corrections to one meeting transcript, then reanalyze.

    This intentionally scopes the blast radius to the selected meeting. It uses the
    same correction chain as ingest: context-aware LLM correction first, then the
    deterministic glossary/normalization pass.
    """
    m = db.get_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.get_meeting(meeting_id)
    if not m:
        raise ValueError(f"meeting {meeting_id} not found")
    original = m.transcript or ""
    corrected_base = correct_terms(original, owner_id=owner_id) if owner_id is not None else correct_terms(original)
    corrected = (
        transcribe.apply_corrections(corrected_base, owner_id=owner_id)
        if owner_id is not None
        else transcribe.apply_corrections(corrected_base)
    )
    original_title = getattr(m, "title", "") or ""
    corrected_title = _apply_glossary_text(original_title, owner_id=owner_id) or original_title
    changed = corrected != original or corrected_title != original_title
    if original_title and corrected_title != original_title:
        if owner_id is not None:
            db.update_meeting_metadata(meeting_id, title=corrected_title, owner_id=owner_id)
        else:
            db.update_meeting_metadata(meeting_id, title=corrected_title)
    out = reanalyze(meeting_id, corrected, owner_id=owner_id) if owner_id is not None else reanalyze(meeting_id, corrected)
    return {**out, "changed": changed}


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
        tokens = [t for t in re.findall(r"[\wÀ-ỹ]+", needle) if len(t) >= 4]
        for token in tokens:
            candidate = hay.find(token)
            if candidate < 0:
                continue
            window = hay[candidate:candidate + max(len(needle) * 2, 120)]
            hits = sum(1 for t in tokens if t in window)
            if hits >= max(2, min(4, len(tokens) // 2)):
                idx = candidate
                break
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


def _fact_citation(fact_id: int | None, owner_id: str | None = None) -> dict | None:
    """Expand a fact id into {statement, quote, meeting_id, meeting_title, date, timestamp}."""
    if not fact_id:
        return None
    f = db.get_fact(fact_id)
    if not f:
        return None
    m = db.get_meeting(f.meeting_id, owner_id=owner_id)
    if not m:
        return None
    return {
        "statement": f.statement,
        "quote": f.quote or "",
        "meeting_id": f.meeting_id,
        "meeting_title": m.title if m else "",
        "date": m.date if m else "",
        "timestamp": estimate_timestamp(m, f.quote or f.statement),
    }


def contradiction_view(owner_id: str | None = None) -> list[dict]:
    """All contradictions enriched for the UI: explanation + both sides' quotes,
    source meeting citations, and approximate listen-back timestamps."""
    out = []
    for c in db.all_contradictions():
        old = _fact_citation(c.fact_a_id, owner_id=owner_id)
        new = _fact_citation(c.fact_b_id, owner_id=owner_id)
        if not old or not new:
            continue
        out.append({
            "subject": c.subject,
            "explanation": c.explanation,
            "severity": c.severity,
            "old": old,   # phát biểu cũ (bị thay thế)
            "new": new,   # phát biểu mới
        })
    return out


# ---------------------------------------------------------------- ask (recall Q&A)

def _relevant_contradictions(question: str, ctx: "retrieve_mod.RetrievedContext",
                             allowed_ids: set[int] | None = None,
                             cap: int = 8) -> list[dict]:
    """Recorded contradictions whose subject overlaps the question or the retrieved
    facts — so Q&A can proactively flag a decision that changed/conflicted over time."""
    topic = retrieve_mod._tokens(question)
    for f in ctx.facts:
        topic |= retrieve_mod._tokens(f.subject)
    if not topic:
        return []
    out = []
    for c in contradiction_view():
        old, new = c.get("old"), c.get("new")
        if allowed_ids is not None and (
            not old or not new or old.get("meeting_id") not in allowed_ids or new.get("meeting_id") not in allowed_ids
        ):
            continue
        if retrieve_mod._tokens(c["subject"]) & topic:
            out.append(c)
        if len(out) >= cap:
            break
    return out


def _contradiction_block(items: list[dict]) -> str:
    """Format relevant recorded contradictions for the Q&A context (empty if none)."""
    if not items:
        return ""
    lines = ["\n### ⚠ MÂU THUẪN ĐÃ GHI NHẬN (liên quan câu hỏi) — "
             "nếu câu trả lời chạm vào các chủ đề này, PHẢI nêu rõ đã từng đổi/mâu thuẫn:"]
    for c in items:
        lines.append(f"- [{c['severity']}] {c['subject']}: {c['explanation']}")
        old, new = c.get("old"), c.get("new")
        if old:
            lines.append(f"    cũ: «{old['statement']}» (meeting_id={old['meeting_id']}, "
                         f"{old['meeting_title']} — {old['date']})")
        if new:
            lines.append(f"    mới: «{new['statement']}» (meeting_id={new['meeting_id']}, "
                         f"{new['meeting_title']} — {new['date']})")
    return "\n".join(lines)


def _strip_extension(value: str) -> str:
    return re.sub(r"\.[a-z0-9]{2,5}$", "", value or "", flags=re.IGNORECASE)


def meeting_group_topic(meeting) -> str:
    """Mirror the sidebar grouping rule: explicit group_title first, title fallback."""
    explicit = (getattr(meeting, "group_title", None) or "").strip()
    if explicit:
        return explicit
    base = _strip_extension(getattr(meeting, "title", None) or getattr(meeting, "source_file", None) or "").strip()
    if not base:
        return "Ungrouped"
    parts = [p.strip() for p in re.split(r"\s[-–—]\s|/|:|\|", base) if p.strip()]
    if len(parts) > 1:
        return parts[0]
    cleaned = re.sub(r"^\d{4}[-_]\d{2}[-_]\d{2}[\s_-]*", "", base, flags=re.IGNORECASE).strip()
    return cleaned or base


def _meeting_scope_ids(meeting_id: int | None, owner_id: str | None = None) -> set[int] | None:
    if not meeting_id:
        if owner_id is None:
            return None
        return {m.id for m in db.list_meetings(limit=10000, owner_id=owner_id)}
    active = db.get_meeting(meeting_id, owner_id=owner_id)
    if not active:
        return set()
    topic = meeting_group_topic(active)
    return {m.id for m in db.list_meetings(limit=10000, owner_id=owner_id) if meeting_group_topic(m) == topic}


def _scope_context(ctx: "retrieve_mod.RetrievedContext", allowed_ids: set[int] | None) -> "retrieve_mod.RetrievedContext":
    if allowed_ids is None:
        return ctx
    if not allowed_ids:
        return retrieve_mod.RetrievedContext()
    scoped_meetings = [m for m in db.list_meetings(limit=10000) if m.id in allowed_ids]
    scoped_meetings = sorted(scoped_meetings, key=lambda m: (m.date or "", m.id or 0))
    scoped_facts = [f for f in ctx.facts if f.meeting_id in allowed_ids]
    return retrieve_mod.RetrievedContext(meetings=scoped_meetings, facts=scoped_facts)


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
        "- Nếu chủ đề câu hỏi xuất hiện trong mục 'MÂU THUẪN ĐÃ GHI NHẬN', hãy MỞ ĐẦU câu trả lời "
        "bằng ĐÚNG tiền tố in nghiêng kiểu markdown '*Mâu thuẫn:*' rồi trình bày diễn biến cũ → "
        "mới (ưu tiên cái mới nhất); đừng trả lời như thể chỉ có một giá trị duy nhất. TUYỆT ĐỐI "
        "KHÔNG dùng chữ 'CẢNH BÁO' hay emoji.\n"
        "- Mỗi ý phải kèm trích nguồn (meeting_id) trong 'citations'; khi có thể, trích câu gốc.\n"
        "- Nếu ngữ cảnh KHÔNG có thông tin, nói rõ 'Chưa từng được đề cập trong các cuộc họp.' "
        "Tuyệt đối không bịa.\n"
        'Trả về DUY NHẤT JSON: {"answer": str, "citations": '
        '[{"meeting_id": int, "quote": str}]}\n\n'
        f"NGỮ CẢNH:\n{context}\n\nCÂU HỎI: {question}"
    )


def ask(question: str, limit: int = 50, meeting_id: int | None = None, owner_id: str | None = None) -> Answer:
    """Historical Recall Q&A, scoped to the active meeting's group/topic when supplied."""
    allowed_ids = _meeting_scope_ids(meeting_id, owner_id=owner_id)
    ctx = _scope_context(retrieve_mod.retrieve(question, limit=limit), allowed_ids)
    if ctx.is_empty():
        return Answer(text="Chưa có cuộc họp nào được ghi nhớ.", citations=[])

    context = _context_block(ctx) + _contradiction_block(_relevant_contradictions(question, ctx, allowed_ids))
    try:
        data = _chat_json(
            _ask_prompt(question, context),
            (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL),
        )
    except ValueError:
        return Answer(text="Xin lỗi, không tạo được câu trả lời lúc này.", citations=[])

    # enrich citations with meeting title/date + approximate listen-back timestamp.
    # Drop citations whose meeting_id isn't a real meeting (model occasionally invents
    # ids) and dedupe by (meeting_id, quote) so the same source isn't listed twice.
    citations: list[Citation] = []
    seen: set[tuple] = set()
    for c in data.get("citations", []):
        mid = c.get("meeting_id")
        m = db.get_meeting(mid) if mid else None
        if allowed_ids is not None and mid not in allowed_ids:
            continue
        if not m:                      # invalid/hallucinated id -> not a usable citation
            continue
        quote = c.get("quote", "")
        key = (mid, quote.strip())
        if key in seen:
            continue
        seen.add(key)
        citations.append(Citation(
            meeting_id=mid,
            meeting_title=m.title,
            date=m.date,
            quote=quote,
            timestamp=estimate_timestamp(m, quote),
        ))
    answer_text = data.get("answer", "").strip() or "Chưa từng được đề cập trong các cuộc họp."
    return Answer(text=answer_text, citations=citations)


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


def _is_overdue(deadline: str | None, today: str | None = None) -> bool:
    """True only for an ISO YYYY-MM-DD deadline strictly before today. Free-text
    deadlines ('cuối Q3') return False — we never guess overdue from prose."""
    if not deadline:
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline.strip()):
        return False
    today = today or _dt.date.today().isoformat()
    return deadline.strip() < today


def _later_meeting_block(m, task: str) -> str:
    """Summary + decisions + task-relevant facts of a later meeting, so follow-up
    judges status from concrete evidence rather than the summary alone."""
    lines = [f"[meeting_id={m.id}] {m.title} ({m.date}): {m.summary}"]
    task_tokens = retrieve_mod._tokens(task)
    try:
        for d in m.report().decisions:
            lines.append(f"   • quyết định: {d.text}")
    except Exception:  # noqa: BLE001 - bad report_json -> skip decisions
        pass
    for f in db.facts_of_meeting(m.id):
        if retrieve_mod._tokens(f.subject) & task_tokens or retrieve_mod._tokens(f.statement) & task_tokens:
            lines.append(f"   • ({f.type}) {f.subject}: {f.statement}")
    return "\n".join(lines)


def follow_up() -> list[dict]:
    """Re-check each not-done action against meetings that happened AFTER it, update
    its status, and record where it was re-mentioned (action_links)."""
    meetings = db.list_meetings(limit=10000)
    by_id = {m.id: m for m in meetings}
    today = _dt.date.today().isoformat()
    results: list[dict] = []

    for a in db.all_actions():
        if a.status == "xong":
            continue
        src = by_id.get(a.meeting_id)
        src_date = src.date if src else ""
        later = [m for m in meetings
                 if (m.id != a.meeting_id) and ((m.date or "") >= (src_date or ""))]
        if not later:
            # no later meetings, but a passed ISO deadline still flips it to overdue
            if _is_overdue(a.deadline, today) and a.status != "quá hạn":
                db.update_action_status(a.id, "quá hạn")
                results.append({"action_id": a.id, "task": a.task, "status": "quá hạn",
                                "note": f"Quá hạn (hạn {a.deadline}), chưa thấy nhắc lại."})
            continue
        later_ctx = "\n".join(_later_meeting_block(m, a.task) for m in later)
        try:
            v = _chat_json(_followup_prompt(a.task, a.owner or "", a.deadline or "", later_ctx),
                           (config.REASONING_MODEL, config.REASONING_FALLBACK_MODEL))
        except ValueError:
            continue
        new_status = v.get("status")
        # deterministic overdue overrides the model UNLESS it found the task done
        if new_status != "xong" and _is_overdue(a.deadline, today):
            new_status = "quá hạn"
        if new_status and new_status != a.status:
            db.update_action_status(a.id, new_status)
        rel = v.get("related_meeting_id")
        if rel and rel in by_id:                # ignore hallucinated meeting ids
            db.add_action_link(a.id, rel, v.get("note", ""))
        results.append({"action_id": a.id, "task": a.task, "status": new_status or a.status,
                        "note": v.get("note", "")})
    return results


def notify_actions(to: list[str] | None = None, refresh: bool = True) -> dict:
    """Email a todo/action reminder. Optionally re-check statuses (follow_up) first.

    Returns a summary with `sent` and a `reason` so callers can tell apart
    "nothing open" from "email disabled/failed".
    """
    if refresh:
        follow_up()                                   # flip "quá hạn", mark "xong"
    actions = db.all_actions()
    titles = {m.id: m.title for m in db.list_meetings(limit=10000)}
    open_items = [a for a in actions if a.status != "xong"]
    sent = mailer.send_action_digest(actions, meeting_titles=titles, to=to)
    reason = ("no_open_items" if not open_items
              else "sent" if sent else "email_disabled")
    return {"sent": sent, "open_items": len(open_items),
            "overdue": sum(1 for a in open_items if a.status == "quá hạn"),
            "reason": reason}


def assign_action(action_id: int, owner: str, email: str | None = None,
                  notify: bool = True, note: str | None = None) -> dict:
    """Set an action's owner and (optionally) email that owner a notification.

    Returns {assigned, owner, sent, reason}. `reason` is one of:
    not_found, no_notify, no_email, sent, email_disabled.
    """
    if not db.update_action_owner(action_id, owner):
        return {"assigned": False, "reason": "not_found"}
    sent, reason = False, "no_notify"
    if notify and email:
        a = db.get_action(action_id)
        m = db.get_meeting(a.meeting_id) if a else None
        sent = mailer.send_assignment(a, email, note=note,
                                      meeting_title=m.title if m else None)
        reason = "sent" if sent else "email_disabled"
    elif notify:
        reason = "no_email"
    return {"assigned": True, "owner": owner, "sent": sent, "reason": reason}
