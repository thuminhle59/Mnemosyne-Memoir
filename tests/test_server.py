from fastapi.testclient import TestClient

from models import Answer, Decision, MeetingReport
import server


def test_api_allows_file_protocol_frontend_origin():
    client = TestClient(server.app)

    response = client.options(
        "/api/ask",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "null"


def test_ingest_rejects_empty_upload_before_pipeline():
    client = TestClient(server.app)

    response = client.post(
        "/api/ingest",
        files={"file": ("empty.mp3", b"", "audio/mpeg")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty"


def test_frontend_assets_are_not_cached_during_local_demo():
    client = TestClient(server.app)

    for path in ["/", "/app.js"]:
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


def test_api_config_exposes_upload_limit_to_frontend():
    client = TestClient(server.app)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["max_upload_bytes"] == server.MAX_UPLOAD_BYTES
    assert response.json()["max_upload_mb"] == server.MAX_UPLOAD_BYTES // (1024 * 1024)


def test_ask_api_passes_active_meeting_scope(monkeypatch):
    captured = {}

    def fake_ask(question, meeting_id=None):
        captured.update({"question": question, "meeting_id": meeting_id})
        return Answer(text="Scoped answer", citations=[])

    monkeypatch.setattr(server.brain, "ask", fake_ask)
    client = TestClient(server.app)

    response = client.post("/api/ask", json={"question": "ngân sách?", "meeting_id": 12})

    assert response.status_code == 200
    assert response.json()["answer"] == "Scoped answer"
    assert captured == {"question": "ngân sách?", "meeting_id": 12}


def test_meeting_detail_estimates_decision_timestamp_from_text_when_quote_missing(monkeypatch):
    class Meeting:
        id = 9
        title = "Pilot"
        date = "2026-06-16"
        duration_sec = 300
        source_file = "meeting.mp3"
        created_at = None
        summary = "summary"
        transcript = "Cả nhóm chốt triển khai Pilot trước."
        group_title = None

        def report(self):
            return MeetingReport(
                title=self.title,
                date=self.date,
                summary=self.summary,
                decisions=[Decision(text="Triển khai Pilot trước", quote=None)],
                full_transcript=self.transcript,
            )

    seen = []
    monkeypatch.setattr(server.db, "facts_of_meeting", lambda meeting_id: [])
    monkeypatch.setattr(server.os.path, "exists", lambda path: False)

    def fake_estimate_timestamp(meeting, candidate):
        seen.append(candidate)
        return "00:12" if candidate == "Triển khai Pilot trước" else None

    monkeypatch.setattr(server.brain, "estimate_timestamp", fake_estimate_timestamp)

    detail = server._meeting_detail(Meeting())

    assert detail["decisions"][0]["quote"] is None
    assert detail["decisions"][0]["timestamp"] == "00:12"
    assert seen == ["Triển khai Pilot trước"]


def test_chunked_upload_exposes_backend_ingest_progress(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(server, "UPLOAD_CHUNK_BYTES", 5)

    init = client.post(
        "/api/uploads",
        json={"filename": "meeting.txt", "size": 10, "content_type": "text/plain"},
    )

    assert init.status_code == 200
    payload = init.json()
    assert payload["job_id"] == payload["upload_id"]
    assert payload["progress_url"] == f"/api/ingest/progress/{payload['job_id']}"

    progress = client.get(payload["progress_url"])
    assert progress.status_code == 200
    assert progress.json()["percent"] == 0
    assert progress.json()["status"] == "running"

    uploaded = client.post(
        f"/api/uploads/{payload['upload_id']}/chunks",
        data={"index": "0"},
        files={"chunk": ("0.part", b"hello", "application/octet-stream")},
    )

    assert uploaded.status_code == 200
    assert uploaded.json()["percent"] == 35
    progress = client.get(payload["progress_url"])
    assert progress.json()["stage"] == "uploading"
    assert progress.json()["percent"] == 35


def test_ingest_text_file_upload_is_treated_as_transcript(monkeypatch):
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)
        return {
            "meeting_id": 7,
            "facts": [],
            "contradictions": [],
            "forgotten": [],
            "report": MeetingReport(
                title="Text file",
                date="2026-06-14",
                summary="Uploaded transcript",
                full_transcript=kwargs["text"],
            ),
        }

    monkeypatch.setattr(server.brain, "ingest", fake_ingest)
    client = TestClient(server.app)

    response = client.post(
        "/api/ingest",
        files={"file": ("meeting.txt", b"Quyet dinh: dung Mnemosyne.", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["meeting_id"] == 7
    assert captured["text"] == "Quyet dinh: dung Mnemosyne."
    assert captured["audio"] is None
    assert captured["source_file"] == "meeting.txt"


def test_meeting_detail_includes_summary_brief():
    mid = server.db.save_meeting(MeetingReport.model_validate({
        "title": "Họp Pilot",
        "date": "2026-06-16",
        "summary": "Cuộc họp chốt Pilot.",
        "summary_brief": {
            "context": "Bàn tiến độ Pilot.",
            "decisions": ["Mở Pilot", "Không Full Rollout"],
            "risk": "Latency còn cao",
            "next_step": "Gửi checklist",
        },
    }))
    client = TestClient(server.app)

    response = client.get(f"/api/meetings/{mid}")

    assert response.status_code == 200
    assert response.json()["summary_brief"] == {
        "context": "Bàn tiến độ Pilot.",
        "decisions": ["Mở Pilot", "Không Full Rollout"],
        "risk": "Latency còn cao",
        "next_step": "Gửi checklist",
    }


def test_owner_header_scopes_meetings_and_detail_access():
    a_id = server.db.save_meeting(
        MeetingReport(title="A meeting", date="2026-06-16", summary="A summary"),
        owner_id="owner-a",
    )
    b_id = server.db.save_meeting(
        MeetingReport(title="B meeting", date="2026-06-16", summary="B summary"),
        owner_id="owner-b",
    )
    client = TestClient(server.app)

    a_list = client.get("/api/meetings", headers={"X-Memoir-Owner": "owner-a"})
    b_detail = client.get(f"/api/meetings/{a_id}", headers={"X-Memoir-Owner": "owner-b"})
    b_list = client.get("/api/meetings", headers={"X-Memoir-Owner": "owner-b"})

    assert a_list.status_code == 200
    assert [m["id"] for m in a_list.json()] == [a_id]
    assert b_detail.status_code == 404
    assert [m["id"] for m in b_list.json()] == [b_id]


def test_owner_scoped_meeting_display_id_starts_from_one():
    other_id = server.db.save_meeting(
        MeetingReport(title="Other owner", date="2026-06-15", summary="Other summary"),
        owner_id="owner-b",
    )
    owner_id = server.db.save_meeting(
        MeetingReport(title="Owner meeting", date="2026-06-16", summary="Owner summary"),
        owner_id="owner-a",
    )
    client = TestClient(server.app)

    listing = client.get("/api/meetings", headers={"X-Memoir-Owner": "owner-a"})
    detail = client.get(f"/api/meetings/{owner_id}", headers={"X-Memoir-Owner": "owner-a"})

    assert other_id != owner_id
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == owner_id
    assert listing.json()[0]["display_id"] == 1
    assert detail.status_code == 200
    assert detail.json()["id"] == owner_id
    assert detail.json()["display_id"] == 1


def test_owner_header_scopes_glossary():
    a_term = server.db.add_glossary("AgentBase", owner_id="owner-a")
    b_term = server.db.add_glossary("OpenClaw", owner_id="owner-b")
    client = TestClient(server.app)

    a_list = client.get("/api/glossary", headers={"X-Memoir-Owner": "owner-a"})
    b_delete_a = client.delete(f"/api/glossary/{a_term}", headers={"X-Memoir-Owner": "owner-b"})
    b_list = client.get("/api/glossary", headers={"X-Memoir-Owner": "owner-b"})

    assert a_list.status_code == 200
    assert [g["term"] for g in a_list.json()] == ["AgentBase"]
    assert b_delete_a.status_code == 404
    assert [g["id"] for g in b_list.json()] == [b_term]


def test_chunked_text_upload_completes_as_transcript(monkeypatch):
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)
        return {
            "meeting_id": 8,
            "facts": [],
            "contradictions": [],
            "forgotten": [],
            "report": MeetingReport(
                title="Chunked text",
                date="2026-06-14",
                summary="Uploaded transcript",
                full_transcript=kwargs["text"],
            ),
        }

    monkeypatch.setattr(server.brain, "ingest", fake_ingest)
    client = TestClient(server.app)
    first_chunk = b"Quyet dinh: dung "
    second_chunk = b"Mnemosyne."
    monkeypatch.setattr(server, "UPLOAD_CHUNK_BYTES", len(first_chunk))

    init = client.post(
        "/api/uploads",
        json={
            "filename": "meeting.md",
            "size": len(first_chunk) + len(second_chunk),
            "content_type": "text/markdown",
        },
    )
    assert init.status_code == 200
    upload_id = init.json()["upload_id"]

    first = client.post(
        f"/api/uploads/{upload_id}/chunks",
        data={"index": "0"},
        files={"chunk": ("0.part", first_chunk, "application/octet-stream")},
    )
    second = client.post(
        f"/api/uploads/{upload_id}/chunks",
        data={"index": "1"},
        files={"chunk": ("1.part", second_chunk, "application/octet-stream")},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    complete = client.post(
        f"/api/uploads/{upload_id}/complete",
        data={"title": "Chunked", "date": "2026-06-14"},
    )

    assert complete.status_code == 200
    assert complete.json()["meeting_id"] == 8
    assert captured["text"] == "Quyet dinh: dung Mnemosyne."
    assert captured["audio"] is None
    assert captured["source_file"] == "meeting.md"
    progress = client.get(f"/api/ingest/progress/{upload_id}")
    assert progress.status_code == 200
    assert progress.json()["percent"] == 100
    assert progress.json()["status"] == "done"


def test_chunked_upload_assembles_parts_without_unbounded_reads(tmp_path):
    parts = []
    for index, content in enumerate([b"hello", b" ", b"world"]):
        path = tmp_path / f"{index}.part"
        path.write_bytes(content)
        parts.append(str(path))
    dest = tmp_path / "assembled.bin"

    size = server._assemble_upload_parts(parts, str(dest))

    assert size == len(b"hello world")
    assert dest.read_bytes() == b"hello world"


def test_audio_upload_is_stored_for_meeting_playback(monkeypatch, tmp_path):
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)
        return {
            "meeting_id": 42,
            "facts": [],
            "contradictions": [],
            "forgotten": [],
            "report": MeetingReport(
                title="Audio meeting",
                date="2026-06-14",
                summary="Uploaded audio",
                full_transcript="Transcript from audio.",
            ),
        }

    monkeypatch.setattr(server, "_WEB", str(tmp_path))
    monkeypatch.setattr(server.brain, "ingest", fake_ingest)
    monkeypatch.setattr(server.media, "to_mp3", lambda data, filename: b"mp3 playback bytes")
    client = TestClient(server.app)

    response = client.post(
        "/api/ingest",
        files={"file": ("meeting.mp3", b"raw audio bytes", "audio/mpeg")},
    )

    assert response.status_code == 200
    assert response.json()["meeting_id"] == 42
    assert captured["audio"] == b"raw audio bytes"
    playback = client.get("/api/meetings/42/audio")
    assert playback.status_code == 200
    assert playback.content == b"raw audio bytes"


def test_video_upload_is_transcoded_for_meeting_playback(monkeypatch, tmp_path):
    def fake_ingest(**kwargs):
        return {
            "meeting_id": 43,
            "facts": [],
            "contradictions": [],
            "forgotten": [],
            "report": MeetingReport(
                title="Video meeting",
                date="2026-06-14",
                summary="Uploaded video",
                full_transcript="Transcript from video.",
            ),
        }

    monkeypatch.setattr(server, "_WEB", str(tmp_path))
    monkeypatch.setattr(server.brain, "ingest", fake_ingest)
    monkeypatch.setattr(server.media, "to_mp3", lambda data, filename: b"mp3 playback bytes")
    client = TestClient(server.app)

    response = client.post(
        "/api/ingest",
        files={"file": ("meeting.mp4", b"raw video bytes", "video/mp4")},
    )

    assert response.status_code == 200
    playback = client.get("/api/meetings/43/audio")
    assert playback.status_code == 200
    assert playback.content == b"mp3 playback bytes"


def test_action_status_endpoint_normalizes_frontend_status(monkeypatch):
    captured = {}

    def fake_update(action_id, status):
        captured["action_id"] = action_id
        captured["status"] = status
        return True

    monkeypatch.setattr(server.db, "update_action_status", fake_update)
    client = TestClient(server.app)

    response = client.patch("/api/actions/12", json={"status": "completed"})

    assert response.status_code == 200
    assert response.json() == {"id": 12, "status": "xong"}
    assert captured == {"action_id": 12, "status": "xong"}


def test_meeting_update_endpoint_renames_display_source_and_group(monkeypatch):
    captured = {}

    def fake_update(meeting_id, title=None, source_file=None, group_title=None):
        captured.update({"meeting_id": meeting_id, "title": title, "source_file": source_file, "group_title": group_title})
        return True

    def fake_get(meeting_id):
        class Meeting:
            id = meeting_id
            title = "Renamed file"
            group_title = "Merchant Portal"
            date = "2026-06-14"
            duration_sec = 12
            source_file = "renamed.mp3"
            created_at = None
            summary = "summary"

        return Meeting()

    monkeypatch.setattr(server.db, "update_meeting_metadata", fake_update)
    monkeypatch.setattr(server.db, "get_meeting", fake_get)
    monkeypatch.setattr(server, "_audio_path", lambda meeting_id: "/tmp/does-not-exist.mp3")
    client = TestClient(server.app)

    response = client.patch(
        "/api/meetings/5",
        json={"title": "Renamed file", "source_file": "renamed.mp3", "group_title": "Merchant Portal"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed file"
    assert response.json()["group_title"] == "Merchant Portal"
    assert captured == {"meeting_id": 5, "title": "Renamed file", "source_file": "renamed.mp3", "group_title": "Merchant Portal"}


def test_group_rename_endpoint_updates_old_group(monkeypatch):
    captured = {}

    def fake_rename(old_group_title, new_group_title):
        captured.update({"old_group_title": old_group_title, "new_group_title": new_group_title})
        return 3

    monkeypatch.setattr(server.db, "rename_meeting_group", fake_rename)
    client = TestClient(server.app)

    response = client.patch(
        "/api/meeting_groups",
        json={"old_group_title": "Nova Portal", "new_group_title": "Merchant Portal"},
    )

    assert response.status_code == 200
    assert response.json() == {"old_group_title": "Nova Portal", "new_group_title": "Merchant Portal", "updated": 3}
    assert captured == {"old_group_title": "Nova Portal", "new_group_title": "Merchant Portal"}


def test_action_detail_uses_task_as_timestamp_fallback_when_quote_is_missing(monkeypatch):
    class Meeting:
        id = 7
        title = "Training"
        date = "2026-06-16"
        duration_sec = 120
        transcript = "Mở đầu. Cài đặt Docker Desktop và đảm bảo mỗi team có ít nhất 1 máy đã set up Docker + GitHub."
        chunk_map = None

    class Action:
        id = 99
        meeting_id = 7
        task = "Cài đặt Docker Desktop và đảm bảo mỗi team có ít nhất 1 máy đã set up Docker + GitHub"
        owner = "Thư"
        deadline = None
        priority = "cao"
        status = "mở"
        quote = None

        def as_dict(self):
            return {
                "id": self.id, "meeting_id": self.meeting_id, "task": self.task,
                "owner": self.owner, "deadline": self.deadline, "priority": self.priority,
                "status": self.status, "quote": self.quote,
            }

    monkeypatch.setattr(server.db, "get_meeting", lambda meeting_id: Meeting())
    detail = server._action_detail(Action())

    assert detail["timestamp"] == "00:10"


def test_glossary_suggestions_extract_unknown_terms(monkeypatch):
    class Meeting:
        id = 9
        title = "AgentBase OpenClaw Sync"
        transcript = "Team nhắc AgentBase, OpenClaw và MCP Server nhiều lần."

        def report(self):
            return MeetingReport(
                title=self.title,
                date="2026-06-15",
                summary="AgentBase and OpenClaw",
                key_points=["Deploy AgentBase runtime"],
                full_transcript=self.transcript,
            )

    monkeypatch.setattr(server.db, "get_meeting", lambda meeting_id: Meeting())
    monkeypatch.setattr(server.db, "facts_of_meeting", lambda meeting_id: [])
    monkeypatch.setattr(server.db, "glossary_terms", lambda: ["OpenClaw"])
    client = TestClient(server.app)

    response = client.get("/api/glossary/suggestions?meeting_id=9")

    assert response.status_code == 200
    terms = [item["term"] for item in response.json()["suggestions"]]
    assert "AgentBase" in terms
    assert "MCP Server" in terms
    assert "OpenClaw" not in terms
    counts = [item["count"] for item in response.json()["suggestions"]]
    assert counts == sorted(counts, reverse=True)


def test_apply_glossary_endpoint_scopes_to_selected_meeting(monkeypatch):
    captured = {}

    def fake_apply(meeting_id):
        captured["meeting_id"] = meeting_id
        return {"meeting_id": meeting_id, "changed": True, "facts": [object()],
                "contradictions": [], "forgotten": []}

    monkeypatch.setattr(server.brain, "apply_glossary_to_meeting", fake_apply)
    client = TestClient(server.app)

    response = client.post("/api/meetings/9/apply_glossary")

    assert response.status_code == 200
    assert response.json()["meeting_id"] == 9
    assert response.json()["changed"] is True
    assert response.json()["facts_count"] == 1
    assert captured == {"meeting_id": 9}
