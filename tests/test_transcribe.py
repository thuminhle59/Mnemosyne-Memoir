"""Tests for STT post-processing (domain-term corrections). No network."""
import transcribe


def test_corrections_fix_contest_name_variants():
    assert transcribe.apply_corrections("Cuộc thi CloudTown") == "Cuộc thi Claw-a-thon"
    assert transcribe.apply_corrections("tham gia Cloud Thorn") == "tham gia Claw-a-thon"
    assert transcribe.apply_corrections("dự án Glow Tone 2026") == "dự án Claw-a-thon 2026"
    assert transcribe.apply_corrections("claw a thon") == "Claw-a-thon"


def test_corrections_fix_brand_terms():
    assert transcribe.apply_corrections("dùng Agent Base") == "dùng AgentBase"
    assert transcribe.apply_corrections("trên Green Node") == "trên GreenNode"
    assert transcribe.apply_corrections("ví Zalo Pay") == "ví ZaloPay"


def test_corrections_fix_vietnamese_phonetic_english_terms():
    text = "Dự án Nô Va Mơ Chăn Pô Tồ đang bàn Pilot Sét tồ mần với Ô pần Claw."
    out = transcribe.apply_corrections(text)
    assert "Nova Merchant Portal" in out
    assert "Pilot Settlement" in out
    assert "OpenClaw" in out


def test_corrections_fix_rollout_and_auto_product_terms():
    text = "Marketing muốn phun rolao nhưng team chỉ đồng ý ô tô pass sét tồ mần."
    out = transcribe.apply_corrections(text)
    assert "Full Rollout" in out
    assert "Auto Pass Settlement" in out


def test_corrections_remove_phonetic_parenthetical_after_canonical_terms():
    text = "Marketing muốn Full Rollout (Phung Rô Lao), không phải Auto Pass (Ô Tô Pass)."
    out = transcribe.apply_corrections(text)
    assert out == "Marketing muốn Full Rollout, không phải Auto Pass."


def test_corrections_keep_meaningful_parenthetical_after_canonical_terms():
    text = "Team chọn Full Rollout (Phase 2) sau Pilot."
    assert transcribe.apply_corrections(text) == text


def test_corrections_do_not_rewrite_normal_car_mentions():
    text = "Bãi xe có nhiều ô tô đang chờ ngoài cổng."
    assert transcribe.apply_corrections(text) == text


def test_corrections_leave_normal_text_unchanged():
    s = "Cuộc họp hôm nay bàn về ngân sách marketing."
    assert transcribe.apply_corrections(s) == s


def test_corrections_apply_org_glossary_mapping():
    import db
    db.add_glossary("Mnemosyne", wrong="nem o din")
    assert "Mnemosyne" in transcribe.apply_corrections("dự án nem o din rất hay")
