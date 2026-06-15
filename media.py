"""Audio extraction + chunking for the STT endpoint.

Two problems this solves:
 1. The managed Whisper endpoint only accepts WAV (RIFF) — it rejects mp3/mp4 with
    "file does not start with RIFF id". So we always transcode to WAV.
 2. A meeting .mp4 carries video (tens/hundreds of MB) and a long call as WAV is big
    too. We strip video, downmix to mono 16 kHz WAV, then split into time chunks so
    each request stays small (avoids 413 / timeout). Transcripts are concatenated.

ffmpeg comes from a system install or the imageio-ffmpeg bundled binary (no brew
needed). WAV splitting uses the stdlib `wave` module — no ffmpeg required.
"""
import io
import shutil
import subprocess
import tempfile
import os
import wave


def _ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def ffmpeg_available() -> bool:
    return _ffmpeg_exe() is not None


def to_wav(data: bytes, src_name: str = "input") -> bytes:
    """Transcode any audio/video bytes to mono 16 kHz 16-bit PCM WAV (drops video)."""
    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg không có trên máy — không thể tách/đổi sang WAV.")
    suffix = os.path.splitext(src_name)[1] or ".bin"
    src = dst = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            src = f.name
        dst = src + ".wav"
        cmd = [exe, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
               "-c:a", "pcm_s16le", dst]
        proc = subprocess.run(cmd, capture_output=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError(f"ffmpeg lỗi: {proc.stderr.decode('utf-8', 'ignore')[-300:]}")
        with open(dst, "rb") as f:
            return f.read()
    finally:
        for p in (src, dst):
            if p and os.path.exists(p):
                os.remove(p)


def to_mp3(data: bytes, src_name: str = "input") -> bytes:
    """Transcode audio/video bytes to MP3 for browser listen-back playback."""
    exe = _ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg không có trên máy — không thể tạo audio playback.")
    suffix = os.path.splitext(src_name)[1] or ".bin"
    src = dst = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            src = f.name
        dst = src + ".mp3"
        cmd = [exe, "-y", "-i", src, "-vn", "-ac", "2", "-ar", "44100",
               "-codec:a", "libmp3lame", "-b:a", "128k", dst]
        proc = subprocess.run(cmd, capture_output=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError(f"ffmpeg lỗi: {proc.stderr.decode('utf-8', 'ignore')[-300:]}")
        with open(dst, "rb") as f:
            return f.read()
    finally:
        for p in (src, dst):
            if p and os.path.exists(p):
                os.remove(p)


def _is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def wav_duration(data: bytes) -> float:
    """Duration in seconds of a WAV blob (0.0 if not parseable WAV)."""
    if not _is_wav(data):
        return 0.0
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:  # noqa: BLE001
        return 0.0


def split_wav(wav_bytes: bytes, chunk_sec: int = 600) -> list[bytes]:
    """Split a WAV into <=chunk_sec pieces, each a valid standalone WAV.
    Returns [wav_bytes] unchanged if it isn't parseable WAV or is short enough."""
    if not _is_wav(wav_bytes):
        return [wav_bytes]
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        nch, sw, fr, nframes = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if nframes <= fr * chunk_sec:
            return [wav_bytes]
        chunks: list[bytes] = []
        per = fr * chunk_sec
        w.rewind()
        remaining = nframes
        while remaining > 0:
            take = min(per, remaining)
            frames = w.readframes(take)
            remaining -= take
            buf = io.BytesIO()
            with wave.open(buf, "wb") as out:
                out.setnchannels(nch)
                out.setsampwidth(sw)
                out.setframerate(fr)
                out.writeframes(frames)
            chunks.append(buf.getvalue())
        return chunks


def audio_to_wav_chunks(data: bytes, src_name: str = "input",
                        chunk_sec: int = 600, do_extract: bool = True) -> list[bytes]:
    """End-to-end: (optionally) transcode to WAV, then split into chunks.
    If extraction is skipped/unavailable and the input is already WAV, it is split
    directly; otherwise the raw bytes are returned as a single chunk."""
    wav = None
    if do_extract and ffmpeg_available():
        wav = to_wav(data, src_name)
    elif _is_wav(data):
        wav = data
    if wav is None:
        return [data]  # last resort: send as-is (may fail if not WAV)
    return split_wav(wav, chunk_sec=chunk_sec)
