"""Mnemosyne — Streamlit front end (primary demo face).

Tabs: Nạp họp (ingest) · Cuộc họp · Chat (recall Q&A) · Action items · Digest.
Runs against the same brain.py the AgentBase endpoint uses, so the demo and the
deployed agent share one brain. Start: streamlit run viewer/app.py
"""
import os
import sys
import time

# make repo root importable when run as `streamlit run viewer/app.py`
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_ROOT, ".env"))

import streamlit as st  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import brain  # noqa: E402
import media  # noqa: E402
import report as report_mod  # noqa: E402

st.set_page_config(page_title="Mnemosyne — ZaloPay Meeting Brain", page_icon="🧠", layout="wide")
db.init_db()

# --- "Warm Editorial Intelligence" design system (Claude Design: Meeting Brain.dc.html) ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"], .stMarkdown, p, span, div, label, input, textarea {
  font-family: 'Hanken Grotesk', system-ui, sans-serif; color: #23201B;
}
.stApp { background: #EFEAE0; }
.block-container { padding-top: 1.8rem; max-width: 1200px; }

/* Editorial serif for headings */
h1, h2, h3, h4 { font-family: 'Newsreader', Georgia, serif !important;
  font-weight: 600 !important; letter-spacing: -0.3px; color: #23201B; }

/* Hero header */
.mb-hero { display:flex; align-items:center; gap:16px; background:#FFFFFF;
  border:1px solid #E4DCCC; border-radius:16px; padding:18px 24px; margin-bottom:16px;
  box-shadow:0 1px 2px rgba(60,50,30,.04); }
.mb-hero .glyph { width:44px; height:44px; border-radius:12px; background:#F6E5DC;
  display:flex; align-items:center; justify-content:center; font-size:24px; }
.mb-hero h1 { margin:0; font-size:24px; }
.mb-hero .sub { font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:1.6px;
  color:#A39A88; text-transform:uppercase; margin-top:3px; }
.mb-hero .tag { font-family:'JetBrains Mono',monospace; font-size:10px; background:#F6E5DC;
  color:#A8452A; padding:3px 9px; border-radius:6px; letter-spacing:.5px; margin-left:auto; }

/* Metric cards */
[data-testid="stMetric"] { background:#FFFFFF; border:1px solid #E4DCCC; border-radius:13px;
  padding:13px 16px; box-shadow:0 1px 2px rgba(60,50,30,.04); }
[data-testid="stMetricLabel"] { font-family:'JetBrains Mono',monospace; font-size:10px !important;
  letter-spacing:1px; text-transform:uppercase; color:#A39A88 !important; }
[data-testid="stMetricValue"] { font-family:'Newsreader',serif; color:#23201B; }

/* Section labels (captions) -> mono uppercase muted */
[data-testid="stCaptionContainer"], .stCaption, [data-testid="stCaptionContainer"] p {
  font-family:'JetBrains Mono',monospace !important; color:#A39A88 !important; letter-spacing:.3px; }

/* Tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap:4px; border-bottom:1px solid #E4DCCC; }
[data-testid="stTabs"] [data-baseweb="tab"] { border-radius:9px 9px 0 0; padding:7px 15px;
  font-weight:600; color:#6B6456; }
[data-testid="stTabs"] [aria-selected="true"] { background:#FFFFFF; color:#A8452A; }

/* Expanders as editorial cards */
[data-testid="stExpander"] { border:1px solid #E4DCCC !important; border-radius:13px !important;
  background:#FFFFFF; margin-bottom:8px; box-shadow:0 1px 2px rgba(60,50,30,.03); }
[data-testid="stExpander"] summary { font-weight:600; }

/* Buttons */
.stButton button, .stDownloadButton button { border-radius:10px; font-weight:600;
  border:1px solid #E4DCCC; background:#FFFFFF; color:#4A443C; }
.stButton button:hover, .stDownloadButton button:hover { border-color:#C65D3B; color:#A8452A; }
.stButton button[kind="primary"] { background:#C65D3B; border-color:#C65D3B; color:#fff;
  box-shadow:0 1px 2px rgba(168,69,42,.3); }
.stButton button[kind="primary"]:hover { background:#A8452A; border-color:#A8452A; color:#fff; }

/* Editorial italic quotes (highlights / evidence) */
blockquote { border-left:3px solid #C65D3B; background:#FBF4EE; border-radius:0 8px 8px 0;
  padding:8px 14px; color:#5A4A1E; font-family:'Newsreader',serif; font-style:italic; font-size:16px; }
code { background:#F0EADD; color:#A8452A; border-radius:5px; padding:1px 6px;
  font-family:'JetBrains Mono',monospace; font-size:12px; }

/* Inputs */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  border-radius:10px; border:1px solid #E4DCCC; background:#FFFFFF; }
[data-baseweb="tab-highlight"] { background:#C65D3B; }
hr { border-color:#E4DCCC; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="mb-hero">
  <div class="glyph">🧠</div>
  <div>
    <h1>Mnemosyne</h1>
    <div class="sub">Meeting Brain · Memory Engine</div>
  </div>
  <span class="tag">ZALOPAY · CLAW-A-THON</span>
</div>
""", unsafe_allow_html=True)
c = db.counts()
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Cuộc họp", c["meetings"])
m2.metric("Fact ghi nhớ", c["facts"])
m3.metric("Action items", c["actions"])
m4.metric("Mâu thuẫn", c["contradictions"])
m5.metric("QĐ tái xuất", c.get("resurfaced", 0))

if not config.LLM_API_KEY:
    st.warning("Chưa có `LLM_API_KEY`. Tạo `.env` từ `.env.example` rồi điền key để dùng các tính năng LLM.")

# proactive contradiction banner — explanation + citations + ≈timestamps
_contras = brain.contradiction_view()
if _contras:
    st.error(f"⚠️ Phát hiện {len(_contras)} mâu thuẫn xuyên cuộc họp:")

    def _side(label, s):
        if not s:
            return
        ts = f" · ⏱ ≈{s['timestamp']}" if s.get("timestamp") else ""
        cite = f"📌 *{s['meeting_title']} ({s['date']})*{ts}"
        st.markdown(f"- **{label}:** {s['statement']}")
        if s.get("quote"):
            st.markdown(f"  > “{s['quote']}”")
        st.caption("  " + cite)

    for cc in _contras:
        with st.expander(f"⚠️ [{cc['severity']}] {cc['subject']}"):
            st.markdown(f"**Giải thích:** {cc['explanation']}")
            _side("Phát biểu cũ", cc["old"])
            _side("Phát biểu mới (hiện tại)", cc["new"])
            if (cc["old"] and cc["old"].get("timestamp")) or (cc["new"] and cc["new"].get("timestamp")):
                st.caption("⏱ Thời điểm là *ước lượng* (endpoint STT không trả timestamp) — tua gần mốc đó để nghe lại.")


# forgotten / resurfaced decisions banner
def _side2(label, s):
    if not s:
        return
    ts = f" · ⏱ ≈{s['timestamp']}" if s.get("timestamp") else ""
    st.markdown(f"- **{label}:** {s['statement']}")
    if s.get("quote"):
        st.markdown(f"  > “{s['quote']}”")
    st.caption(f"  📌 *{s['meeting_title']} ({s['date']})*{ts}")


_resurf = brain.resurfaced_view()
_kind_label = {"rejected": "Đã từng bị BÁC, nay nhắc lại", "forgotten": "Đã nêu rồi BỎ QUÊN, nay nhắc lại"}
if _resurf:
    st.warning(f"🔁 {len(_resurf)} quyết định/chủ đề **tái xuất** (từng bị bác hoặc bị bỏ quên):")
    for r in _resurf:
        with st.expander(f"🔁 [{_kind_label.get(r['kind'], r['kind'])}] {r['subject']}"):
            st.markdown(f"**Giải thích:** {r['explanation']}")
            _side2("Lần trước", r["old"])
            _side2("Lần nhắc lại (hiện tại)", r["new"])
if c["meetings"] > 1 and st.button("🔁 Rà soát lại quyết định tái xuất (toàn bộ)"):
    with st.spinner("Đang rà soát quyết định bị bác/bỏ quên nay nhắc lại..."):
        brain.scan_forgotten()
    st.rerun()

tab_ingest, tab_meetings, tab_chat, tab_actions, tab_digest, tab_glossary = st.tabs(
    ["➕ Nạp họp", "📋 Cuộc họp", "💬 Chat", "✅ Action items", "📊 Digest", "📚 Từ điển"]
)

# ---------------------------------------------------------------- ingest
with tab_ingest:
    # show the result of the previous ingest (survives the st.rerun below)
    _msg = st.session_state.pop("ingest_msg", None)
    if _msg:
        (st.info if _msg.get("skipped") else st.success)(_msg["text"])
        for cline in _msg.get("contradictions", []):
            st.markdown(cline)

    st.subheader("Nạp một cuộc họp vào bộ nhớ")
    st.caption("⚠️ Chỉ dùng dữ liệu họp giả lập / cá nhân (tuân thủ rulebook Claw-a-thon).")
    title = st.text_input("Tiêu đề cuộc họp", "")
    date = st.text_input("Ngày họp (YYYY-MM-DD)", "")
    mode = st.radio("Nguồn", ["Dán transcript", "Tải audio/video"], horizontal=True)
    transcript_text, audio_bytes, upload_name, do_extract = "", None, "meeting.wav", True
    on_duplicate, dup = "new", None
    if mode == "Dán transcript":
        transcript_text = st.text_area("Transcript", height=220)
    else:
        up = st.file_uploader(
            "Audio / Video (.wav .mp3 .m4a .mp4 .webm .aiff)",
            type=["wav", "mp3", "m4a", "mp4", "webm", "aiff", "ogg"],
        )
        if up:
            audio_bytes = up.read()
            upload_name = up.name
            st.caption(f"Đã chọn: {up.name} ({len(audio_bytes)/1024/1024:.1f} MB)")
            do_extract = st.checkbox(
                "🎬 Tách audio + đổi sang WAV bằng ffmpeg (khuyên dùng — endpoint chỉ nhận WAV)",
                value=True,
                help="Bỏ video, đổi sang WAV mono 16kHz và cắt thành đoạn để transcribe. "
                     "Bỏ chọn chỉ khi bạn upload sẵn file .wav.",
            )
            if do_extract and not media.ffmpeg_available():
                st.error("Không tìm thấy ffmpeg (kể cả bản imageio-ffmpeg). "
                         "Cài `pip install imageio-ffmpeg` trong venv rồi thử lại.")
            # same-file detection
            dup = db.find_by_audio_hash(db.audio_hash(audio_bytes))
            if dup:
                st.warning(f"⚠️ File này đã được nạp rồi → cuộc họp **#{dup.id} '{dup.title}'**. "
                           f"Bạn muốn xử lý thế nào?")
                _choice = st.radio(
                    "Trùng file:",
                    ["Bỏ qua (không nạp lại)", "Ghi đè cuộc họp cũ", "Lưu thành cuộc họp mới"],
                    index=0, horizontal=True,
                )
                on_duplicate = {"Bỏ qua (không nạp lại)": "skip",
                                "Ghi đè cuộc họp cũ": "overwrite",
                                "Lưu thành cuộc họp mới": "new"}[_choice]

    if st.button("Nạp vào bộ nhớ", type="primary"):
        try:
            t0 = time.time()
            with st.spinner("Đang đổi WAV / cắt đoạn / transcribe / phân tích / trích fact / dò mâu thuẫn..."):
                out = brain.ingest(
                    text=transcript_text or None, audio=audio_bytes,
                    date=date or None,
                    title=title or (dup.title if dup else None),   # giữ tên cũ nếu trùng file
                    filename=upload_name, extract=do_extract,
                    source_file=(upload_name if audio_bytes else None),
                    on_duplicate=on_duplicate,
                )
            elapsed = time.time() - t0
            if out.get("skipped"):
                msg = {"skipped": True,
                       "text": f"⏭️ Đã bỏ qua — file này đã có trong bộ nhớ (cuộc họp #{out['meeting_id']})."}
            else:
                msg = {"skipped": False,
                       "text": f"✅ Đã vào bộ nhớ: cuộc họp #{out['meeting_id']} — "
                               f"{len(out['facts'])} fact · ⏱ thời gian xử lý {elapsed:.1f}s",
                       "contradictions": (
                           ([f"⚠️ **{len(out['contradictions'])} mâu thuẫn mới:**"]
                            + [f"- **{cc.subject}**: {cc.explanation}" for cc in out["contradictions"]]
                            if out["contradictions"] else [])
                           + ([f"🔁 **{len(out.get('forgotten', []))} quyết định tái xuất:**"]
                              + [f"- **{fg['subject']}** ({fg['kind']}): {fg['explanation']}"
                                 for fg in out.get("forgotten", [])]
                              if out.get("forgotten") else []))}
            st.session_state["ingest_msg"] = msg
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.exception(e)

# ---------------------------------------------------------------- meetings
def _fmt_dt(dt):
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return "-"


with tab_meetings:
    st.subheader("Các cuộc họp đã ghi nhớ")
    meetings = db.list_meetings()
    if not meetings:
        st.info("Chưa có cuộc họp nào. Sang tab 'Nạp họp' để bắt đầu.")
    for m in meetings:
        src = m.source_file or "— (dán transcript)"
        header = f"#{m.id} · {m.title}  ·  📄 {src}  ·  🕒 {_fmt_dt(m.created_at)}"
        with st.expander(header):
            rep = m.report()
            has_audio = bool(m.duration_sec)

            def _ts(quote, _m=m, _has=has_audio):
                if not _has or not quote:
                    return ""
                t = brain.estimate_timestamp(_m, quote)
                return f" `⏱≈{t}`" if t else ""

            # meta line
            meta_bits = [f"📅 {m.date}"]
            if has_audio:
                mm, ss = divmod(m.duration_sec, 60)
                meta_bits.append(f"🎧 ~{mm:02d}:{ss:02d}")
            st.caption(" · ".join(meta_bits) + ("  ·  ⏱ là mốc *ước lượng* để tua nghe lại." if has_audio else ""))

            # ---- readable summary/report ----
            st.markdown(f"### 📝 Tóm tắt\n{rep.summary}")
            if rep.key_points:
                st.markdown("**🔑 Ý chính**")
                for k in rep.key_points:
                    st.markdown(f"- {k}")
            if rep.decisions:
                st.markdown("**✅ Quyết định**")
                for d in rep.decisions:
                    st.markdown(f"- {d.text}{_ts(d.quote)}")
            if rep.action_items:
                st.markdown("**📌 Action items**")
                for a in rep.action_items:
                    who = f" — 👤 {a.owner}" if a.owner else ""
                    when = f" · ⏳ {a.deadline}" if a.deadline else ""
                    st.markdown(f"- {a.task}{who}{when}{_ts(a.quote)}")
            if rep.risks:
                st.markdown("**⚠️ Rủi ro / Blocker**")
                for r in rep.risks:
                    st.markdown(f"- {r}")

            # ---- raw transcript: editable, re-analyze on save ----
            with st.expander("📜 Transcript (sửa được → Lưu để phân tích lại)"):
                edited = st.text_area("Transcript", value=m.transcript or "", height=260,
                                      key=f"tr_{m.id}", label_visibility="collapsed")
                if st.button("💾 Lưu & phân tích lại", key=f"save_{m.id}"):
                    with st.spinner("Đang phân tích lại transcript đã sửa..."):
                        brain.reanalyze(m.id, edited)
                    st.session_state["ingest_msg"] = {"skipped": False,
                                                      "text": f"✅ Đã phân tích lại cuộc họp #{m.id}."}
                    st.rerun()

            # ---- downloads + delete ----
            col_dl, col_del = st.columns([3, 1])
            with col_dl:
                for fmt in ("docx", "pdf"):
                    try:
                        data = report_mod.render_docx(rep) if fmt == "docx" else report_mod.render_pdf(rep)
                        st.download_button(f"Tải {fmt.upper()}", data,
                                           file_name=report_mod.filename(rep, fmt), key=f"{m.id}-{fmt}")
                    except Exception:  # noqa: BLE001 - pdf libs may be missing locally
                        pass
            with col_del:
                if st.checkbox("Xác nhận xoá", key=f"cfm_{m.id}"):
                    if st.button("🗑 Xoá cuộc họp", key=f"del_{m.id}"):
                        db.delete_meeting(m.id)
                        st.session_state["ingest_msg"] = {"skipped": True,
                                                          "text": f"🗑 Đã xoá cuộc họp #{m.id}."}
                        st.rerun()

# ---------------------------------------------------------------- chat
_SUGGESTED = [
    "Tóm tắt các quyết định chính",
    "Có mâu thuẫn nào giữa các cuộc họp không?",
    "Những action item nào đang còn mở?",
    "Quyết định nào từng bị bác nay được nhắc lại?",
]
with tab_chat:
    st.subheader("Hỏi đáp xuyên lịch sử (Historical Recall)")
    st.caption("MULTI-MEETING · hỏi xuyên toàn bộ cuộc họp đã ghi nhớ")

    # suggested questions (design: 'Suggested')
    scols = st.columns(2)
    for i, s in enumerate(_SUGGESTED):
        if scols[i % 2].button(s, key=f"sug_{i}"):
            st.session_state["chatbox"] = s
            st.session_state["run_q"] = True
            st.rerun()

    q = st.text_input("Câu hỏi", key="chatbox", placeholder="Hỏi bất cứ điều gì về các cuộc họp…")
    do_run = st.button("Hỏi", type="primary") or st.session_state.pop("run_q", False)
    if do_run and q.strip():
        with st.spinner("Đang lục lại ký ức các cuộc họp..."):
            ans = brain.ask(q)
        st.markdown(ans.text)
        if ans.citations:
            st.markdown("**Nguồn (bấm ⏱ để biết mốc nghe lại):**")
            for ci in ans.citations:
                label = f"#{ci.meeting_id} · {ci.meeting_title} ({ci.date})"
                ts = f" `⏱≈{ci.timestamp}`" if ci.timestamp else ""
                st.markdown(f"- {label}{ts}")
                if ci.quote:
                    st.markdown(f"  > {ci.quote}")

# ---------------------------------------------------------------- actions
with tab_actions:
    st.subheader("Action items (theo dõi xuyên cuộc họp)")
    if st.button("🔄 Chạy follow-up (đối chiếu trạng thái)"):
        with st.spinner("Đang đối chiếu action xuyên các cuộc họp..."):
            brain.follow_up()
        st.rerun()
    actions = db.all_actions()
    if not actions:
        st.info("Chưa có action item nào.")
    else:
        rows = []
        for a in actions:
            overdue = a.status == "quá hạn"
            rows.append({
                "Việc": a.task, "Người": a.owner or "-", "Hạn": a.deadline or "-",
                "Trạng thái": ("🔴 " if overdue else "") + a.status,
                "Họp #": a.meeting_id,
            })
        st.dataframe(rows, width="stretch", hide_index=True)

# ---------------------------------------------------------------- digest
with tab_digest:
    st.subheader("Executive Digest")
    if st.button("Tạo digest", type="primary"):
        with st.spinner("Đang tổng hợp digest điều hành..."):
            rep = brain.digest("all")
        st.markdown(f"### {rep.title}")
        st.markdown(rep.summary)
        if rep.key_points:
            st.markdown("**Điểm chính:**")
            for k in rep.key_points:
                st.markdown(f"- {k}")
        if rep.risks:
            st.markdown("**Rủi ro / Mâu thuẫn:**")
            for r in rep.risks:
                st.markdown(f"- {r}")
        try:
            st.download_button("Tải digest DOCX", report_mod.render_docx(rep),
                               file_name=report_mod.filename(rep, "docx"))
        except Exception:  # noqa: BLE001
            pass

# ---------------------------------------------------------------- glossary / training guide
def _read_guide(up) -> str:
    name = up.name.lower()
    data = up.read()
    if name.endswith(".docx"):
        try:
            import io
            import docx
            return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
        except Exception:  # noqa: BLE001
            return ""
    return data.decode("utf-8", "ignore")


with tab_glossary:
    st.subheader("📚 Từ điển tổ chức (training guide)")
    st.caption("Dạy agent các tên riêng / thuật ngữ của team/dự án để transcribe đúng cho mọi file audio.")

    st.markdown("**Cách 1 — Tải file hướng dẫn** (.txt / .md / .docx): agent tự trích thuật ngữ.")
    guide = st.file_uploader("File guide", type=["txt", "md", "docx"], key="guide_up")
    if guide and st.button("📖 Học thuật ngữ từ file", type="primary"):
        gtext = _read_guide(guide)
        if not gtext.strip():
            st.error("Không đọc được nội dung file.")
        else:
            with st.spinner("Đang trích thuật ngữ..."):
                learned = brain.learn_glossary(gtext)
            st.success(f"Đã học {len(learned)} thuật ngữ: {', '.join(learned[:30])}")
            st.rerun()

    st.markdown("**Cách 2 — Dán danh sách thuật ngữ** (mỗi dòng 1 từ):")
    pasted = st.text_area("Thuật ngữ", height=100, key="gloss_paste")
    if st.button("➕ Thêm thuật ngữ"):
        n = 0
        for line in pasted.splitlines():
            if line.strip():
                db.add_glossary(line.strip()); n += 1
        st.success(f"Đã thêm {n} thuật ngữ."); st.rerun()

    st.markdown("**Cách 3 — Sửa nghe nhầm cố định** (nghe nhầm → đúng):")
    cwrong, cright = st.columns(2)
    w = cwrong.text_input("Nghe nhầm (vd: cloud town)", key="fix_wrong")
    r = cright.text_input("Đúng (vd: Claw-a-thon)", key="fix_right")
    if st.button("➕ Thêm mapping") and r.strip():
        db.add_glossary(r.strip(), wrong=w.strip() or None)
        st.success("Đã thêm mapping."); st.rerun()

    st.divider()
    rows = db.list_glossary()
    st.markdown(f"**Từ điển hiện có ({len(rows)}):**")
    if not rows:
        st.info("Chưa có thuật ngữ nào.")
    for g in rows:
        c1, c2 = st.columns([5, 1])
        label = f"`{g.wrong}` → **{g.term}**" if g.wrong else f"**{g.term}**"
        c1.markdown(label)
        if c2.button("🗑", key=f"gd_{g.id}"):
            db.delete_glossary(g.id); st.rerun()
