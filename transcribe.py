"""Speech-to-text via GreenNode-managed Whisper Large V3 (model-scoped route).

Verified: endpoint returns {"text": ..., "logprobs": null} with no segments.
Domain proper nouns Whisper mishears are fixed in post-processing (config.STT_CORRECTIONS).
"""
import json
import re
import urllib.request
import urllib.error
import uuid
import config


def apply_corrections(text: str, owner_id: str | None = None) -> str:
    """Deterministic regex cleanup, run AFTER the LLM correction (brain.correct_terms):
      NORMALIZE  — always: canonical spelling (ZaloPay, AgentBase...).
      TERM FIXES — if STT_FIX_TERMS: mis-heard word -> proper noun
                   (CloudTown -> Claw-a-thon). Off-able for unknown topics.
    This is the final guarantee that known terms end up in canonical form.
    """
    for pattern, repl in config.STT_NORMALIZE:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    if config.STT_FIX_TERMS:
        for pattern, repl in config.STT_TERM_FIXES:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        # user-taught mappings from the org glossary (wrong -> correct)
        for wrong, term in _glossary_fixes(owner_id=owner_id):
            pat = r"\b" + re.escape(wrong).replace(r"\ ", r"[\s-]?") + r"\b"
            text = re.sub(pat, term, text, flags=re.IGNORECASE)
    return text


def _glossary_fixes(owner_id: str | None = None) -> list[tuple[str, str]]:
    try:
        import db
        return db.glossary_fixes(owner_id=owner_id)
    except Exception:  # noqa: BLE001 - DB not ready / no glossary
        return []


def transcribe(audio_bytes: bytes, filename: str = "audio.wav", language: str = "vi",
               prompt: str | None = None) -> str:
    """STT one audio file. `prompt` biases Whisper toward correct spelling of
    domain proper nouns (Claw-a-thon, ZaloPay, AgentBase...) — defaults to
    config.STT_PROMPT. Whisper only reads ~224 prompt tokens, so keep it a short
    glossary; it is re-sent for every chunk of a long recording."""
    if not audio_bytes:
        raise ValueError("empty audio")
    if prompt is None:
        prompt = config.STT_PROMPT
    boundary = f"----mghost-{uuid.uuid4().hex}"

    def _field(name: str, value: str) -> bytes:
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()

    body = _field("model", config.STT_MODEL) + _field("language", language)
    if prompt:
        body += _field("prompt", prompt)
    body += (
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
         f'Content-Type: application/octet-stream\r\n\r\n').encode()
        + audio_bytes + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        config.STT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:500]
        size_mb = len(audio_bytes) / 1024 / 1024
        raise RuntimeError(
            f"STT HTTP {e.code} {e.reason} (audio {size_mb:.1f} MB). Phản hồi: {body}"
        ) from e
    except urllib.error.URLError as e:
        size_mb = len(audio_bytes) / 1024 / 1024
        raise RuntimeError(
            f"STT không kết nối/timeout (audio {size_mb:.1f} MB): {e.reason}"
        ) from e
    # Return RAW text; correction ordering (LLM first, then regex) is orchestrated
    # by brain.ingest so the layers run in the intended sequence.
    return data.get("text", "").strip()
