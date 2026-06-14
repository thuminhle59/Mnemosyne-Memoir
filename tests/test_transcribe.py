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


def test_corrections_leave_normal_text_unchanged():
    s = "Cuộc họp hôm nay bàn về ngân sách marketing."
    assert transcribe.apply_corrections(s) == s


def test_corrections_apply_org_glossary_mapping():
    import db
    db.add_glossary("Mnemosyne", wrong="nem o din")
    assert "Mnemosyne" in transcribe.apply_corrections("dự án nem o din rất hay")
