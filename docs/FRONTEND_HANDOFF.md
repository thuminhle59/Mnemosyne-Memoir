# Mnemosyne / Memoir — Frontend Handoff

> Bản giao cho người dựng **frontend** (ví dụ ChatGPT). Backend đã xong và **giữ nguyên** —
> bạn chỉ cần dựng UI gọi REST API mô tả dưới đây. Sản phẩm: **ZaloPay Meeting Brain**
> ("Mnemosyne", API title hiện là "Memoir") — bộ nhớ tổ chức cho các cuộc họp.

## 1. Kiến trúc (đã cố định)

```
Browser (frontend cần dựng)  ──fetch──►  FastAPI (server.py)  ──►  brain.py (logic, BẤT BIẾN)
                                                                      └► SQLite (memory)
```
- Backend = **lớp API mỏng** (`server.py`) bọc `brain.py`. Không có business logic ở API.
- Frontend là **SPA tĩnh** đặt trong `web/`, server phục vụ ở `/`. Mọi dữ liệu qua `/api/*`.
- Mọi response là **JSON**. Base URL = cùng origin (vd `http://127.0.0.1:8080` khi dev, hoặc
  endpoint AgentBase khi deploy). Không cần auth ở tầng này.
- Khuyến nghị frontend: **React no-build** (React UMD + Babel standalone, file `.jsx` tĩnh) +
  một `api-bridge.js` map shape — đây là pattern đã chạy thật trên AgentBase.

## 2. Định hướng thiết kế (đã chốt) — "Warm Editorial Intelligence"
Tham khảo file `design/Meeting Brain.dc.html` + `design/screenshots/` trong gói này.
- **Màu:** nền giấy kem `#EFEAE0`; card trắng viền `#E4DCCC`; mực ấm `#23201B`;
  accent **terracotta `#C65D3B`** (đậm `#A8452A`); badge peach `#F6E5DC`; highlight gold `#B89B4A`.
- **Font:** `Newsreader` (serif, tiêu đề + TL;DR + highlight italic) · `Hanken Grotesk` (UI/body) ·
  `JetBrains Mono` (label/section uppercase + timestamp).
- **Layout gốc:** desktop 3 cột — trái: Library (danh sách họp) + Terminology + Connected;
  giữa: Transcript (speaker turns + tag + audio scrubber) + Summary/Digest + Export bar;
  phải: Chat Q&A (citations + suggested + multi-meeting toggle). Modal "New meeting" để nạp.

## 3. API reference (đầy đủ)

Tất cả dưới tiền tố `/api`. Lỗi trả `{"detail": "..."}` với mã 4xx.

### Đọc
| Method · Path | Trả về |
|---|---|
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/config` | `{"max_upload_bytes":int,"max_upload_mb":int,"upload_chunk_bytes":int}` |
| `GET /api/stats` | `{"meetings":int,"facts":int,"actions":int,"contradictions":int,"resurfaced":int}` |
| `GET /api/meetings` | `[MeetingBrief]` |
| `GET /api/meetings/{id}` | `MeetingDetail` (404 nếu không có) |
| `GET /api/meetings/{id}/audio` | file mp3 (404 nếu chưa lưu audio — tính năng nghe lại, có thể chưa bật) |
| `GET /api/actions?status=` | `[Action]` |
| `GET /api/contradictions` | `[ContradictionView]` |
| `GET /api/resurfaced` | `[ResurfacedView]` |
| `GET /api/digest?scope=all` | `Digest` |
| `GET /api/glossary` | `[GlossaryItem]` |

### Ghi
| Method · Path | Body | Trả về |
|---|---|---|
| `POST /api/ask` | `{"question": str}` | `{"answer": str, "citations": [Citation]}` |
| `POST /api/ingest` | multipart: `file`?, `text`?, `title`?, `date`?, `on_duplicate`(skip\|overwrite\|new), `extract`(bool) | `IngestResult` |
| `POST /api/ingest/check` | multipart: `file` | `{"duplicate": bool, "meeting": MeetingBrief\|null}` |
| `POST /api/uploads` | `{"filename":str,"size":int,"content_type":str?}` | `{"upload_id":str,"chunk_size":int,"total_chunks":int}` |
| `POST /api/uploads/{id}/chunks` | multipart: `index`(int), `chunk`(file) | `{"received": int}` |
| `POST /api/uploads/{id}/complete` | multipart: `text`?,`title`?,`date`?,`on_duplicate`,`extract` | `IngestResult` |
| `POST /api/meetings/{id}/reanalyze` | `{"transcript": str}` | `{"meeting_id":int,"facts_count":int,"contradictions":[...],"forgotten":[...]}` |
| `DELETE /api/meetings/{id}` | — | `{"status":"deleted","meeting_id":int}` |
| `POST /api/followup` | — | `{"updates": [...]}` |
| `POST /api/scan_forgotten` | — | `{"resurfaced": [Forgotten]}` |
| `POST /api/glossary` | `{"term":str,"wrong":str?}` | `{"id": int}` |
| `POST /api/glossary/learn` | multipart: `file` (.txt/.md) | `{"terms":[str]}` |
| `DELETE /api/glossary/{id}` | — | `{"status":"deleted","id":int}` |

### Upload file lớn (audio/video họp dài)
- File nhỏ → dùng thẳng `POST /api/ingest` (multipart, field `file`).
- File lớn → **chunked**: `POST /api/uploads` (khởi tạo) → lặp `POST /api/uploads/{id}/chunks`
  với `index` 0..n-1 và `chunk` = `chunk_size` byte → `POST /api/uploads/{id}/complete`.
- Trước khi nạp nên gọi `POST /api/ingest/check` để cảnh báo **trùng file** (cho user chọn
  bỏ qua / ghi đè / lưu mới qua `on_duplicate`).
- File `.txt`/`.md` được xem là **transcript** (không transcribe). Audio/video sẽ được
  transcode WAV + cắt đoạn + STT ở backend (có thể mất vài phút cho họp dài).

## 4. Data shapes (JSON)

```jsonc
// MeetingBrief
{"id":1,"title":"Họp tuần 1","date":"2026-06-02","duration_sec":640,
 "source_file":"hop1.mp4","created_at":"2026-06-14T05:30:00+00:00","summary":"..."}

// MeetingDetail = MeetingBrief + ↓
{"transcript":"...", "key_points":["..."],
 "decisions":[{"text":"...","quote":"...","timestamp":"12:34"}],          // timestamp ≈ mm:ss, có thể null
 "action_items":[{"task":"...","owner":"An","deadline":"2026-06-05","status":"mở","quote":"...","timestamp":"08:10"}],
 "risks":["..."],
 "facts":[{"type":"quyết định","subject":"ngày launch","statement":"30/6","quote":"...","status":"hiệu lực","timestamp":"05:00"}]}

// Citation (trong answer)
{"meeting_id":2,"meeting_title":"Họp tuần 2","date":"2026-06-09","quote":"...","timestamp":"15:20"}

// ContradictionView
{"subject":"ngày launch","explanation":"30/6 vs 15/7","severity":"cao",
 "old":{Citation-like},"new":{Citation-like}}   // old/new gồm statement,quote,meeting_id,meeting_title,date,timestamp

// ResurfacedView  (kind: "rejected" | "forgotten")
{"subject":"tính năng X","kind":"rejected","explanation":"...","old":{...},"new":{...}}

// Action
{"id":3,"meeting_id":1,"task":"...","owner":"An","deadline":"...","status":"mở"}

// Digest
{"title":"Executive Digest (all)","summary":"...","key_points":["..."],
 "decisions":["..."],"risks":["..."],"action_items":[{"task":"...","owner":"...","deadline":"...","status":"..."}]}

// IngestResult
{"meeting_id":4,"skipped":false,"facts_count":9,
 "contradictions":[{"subject":"...","explanation":"...","severity":"cao"}],
 "forgotten":[{"subject":"...","kind":"rejected","explanation":"..."}],
 "elapsed_sec":74.5,"report":{MeetingReport}}

// GlossaryItem  (wrong=null → term thường; wrong set → mapping nghe-nhầm→đúng)
{"id":1,"wrong":"cloud town","term":"Claw-a-thon"}
```

`status` của action: `mở | đang làm | xong | quá hạn | treo`.
`fact.type`: `quyết định | fact | cam kết | số liệu | giả định | rủi ro`.
`fact.status`: `hiệu lực | đã thay thế | mâu thuẫn`.

## 5. Lưu ý quan trọng cho người dựng frontend

1. **≈timestamp là ƯỚC LƯỢNG** (endpoint Whisper không trả timestamp thật). Luôn hiển thị
   dấu `≈` và nhãn "ước lượng". Chỉ có với cuộc họp nạp từ **audio** (transcript dán thì null).
2. **CHƯA có kết nối trực tiếp Teams / Google Meet / Zoom.** Các nút "Connect" trong design
   hiện là **mock / tính năng tương lai** — đừng wire vào API thật. Nguồn nạp thật chỉ gồm:
   **upload file** (audio/video/txt) và **dán transcript**.
3. `GET /api/meetings/{id}/audio` có thể **404** đến khi backend bật lưu audio → ẩn audio
   scrubber nếu 404.
4. Backend STT không trả **speaker** và **segment-level timestamp** → transcript là 1 khối text;
   hiển thị theo đoạn + tag (lấy từ `facts`) thay vì speaker-turns chính xác.
5. Tính năng tương ứng các phần của design:
   - **Transcript/Highlights/Decisions/Actions** → `GET /api/meetings/{id}` (+`/digest`).
   - **Chat Q&A + citations** → `POST /api/ask`. Suggested questions: tự đặt sẵn ở FE.
   - **Multi-meeting**: `ask` vốn đã truy vấn xuyên toàn bộ họp → toggle chỉ là nhãn UI.
   - **Mâu thuẫn / Quyết định tái xuất** → `/api/contradictions`, `/api/resurfaced` (+`scan_forgotten`).
   - **Terminology/Training guide** → `/api/glossary*`.
   - **Export** (Copy/PDF/Email): PDF/DOCX nên gọi backend report (chưa expose qua /api —
     có thể thêm sau); Copy/Email làm phía FE.

## 6. Chạy backend để test FE
```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # điền LLM_API_KEY (GreenNode MaaS)
uvicorn server:app --host 0.0.0.0 --port 8080   # API tại /api/*, FE tại /
# Swagger để thử nhanh: http://127.0.0.1:8080/docs
```
Đặt frontend build xong vào thư mục `web/` (có `index.html`) — server tự phục vụ ở `/`.
