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
