from fastapi.testclient import TestClient

from models import MeetingReport
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


def test_meeting_update_endpoint_renames_display_and_source(monkeypatch):
    captured = {}

    def fake_update(meeting_id, title=None, source_file=None):
        captured.update({"meeting_id": meeting_id, "title": title, "source_file": source_file})
        return True

    def fake_get(meeting_id):
        class Meeting:
            id = meeting_id
            title = "Renamed file"
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
        json={"title": "Renamed file", "source_file": "renamed.mp3"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed file"
    assert captured == {"meeting_id": 5, "title": "Renamed file", "source_file": "renamed.mp3"}


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
