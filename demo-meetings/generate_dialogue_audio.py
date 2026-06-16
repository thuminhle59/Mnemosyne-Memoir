"""Generate a multi-voice demo audio from a meeting transcript.

Only the spoken dialogue lines (Linh:/Minh:/An:) are voiced — section
titles, timecodes and "Quyết định ghi nhận" notes are skipped. Each
speaker gets a distinct voice so the recording sounds like a real meeting.

Usage:
    python generate_dialogue_audio.py "2026-05-01 deploy ZenoPay Merchant Portal.txt"
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg

OUT_DIR = Path(__file__).resolve().parent
SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2
PAUSE_SECONDS = 0.45  # gap between turns

# Each speaker -> (voice, rate, pitch). Two VN voices exist; An is given a
# higher, slightly faster female voice to stay distinct from Linh.
SPEAKERS = {
    "Linh": {"voice": "vi-VN-HoaiMyNeural", "rate": "+0%", "pitch": "+0Hz"},
    "An": {"voice": "vi-VN-HoaiMyNeural", "rate": "+8%", "pitch": "+22Hz"},
    "Minh": {"voice": "vi-VN-NamMinhNeural", "rate": "-2%", "pitch": "-2Hz"},
}

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def parse_dialogue(content: str) -> list[tuple[str, str]]:
    """Return [(speaker, text)] keeping only real character dialogue."""
    turns: list[tuple[str, str]] = []
    for raw in content.splitlines():
        line = raw.strip()
        m = re.match(r"^(Linh|Minh|An):\s*(.+)$", line)
        if m:
            turns.append((m.group(1), m.group(2).strip()))
    return turns


# English/technical terms respelled phonetically so the Vietnamese neural
# voices pronounce them naturally. Ordered: multi-word phrases first so they
# match before the single words they contain. Only affects the spoken audio —
# the .txt transcript stays unchanged.
PRONUNCIATION = [
    # multi-word phrases first
    ("RC zero point nine", "a-xê không chấm chín"),
    ("Auto Settlement", "ô-tô sét-tồ-mừn"),
    ("auto settlement", "ô-tô sét-tồ-mừn"),
    ("settlement summary", "sét-tồ-mừn sâm-mơ-ri"),
    ("settlement view", "sét-tồ-mừn viu"),
    ("settlement failed", "sét-tồ-mừn phây"),
    ("feature flag", "phi-chơ phờ-lác"),
    ("full rollout", "phun rô-lao"),
    ("go-live", "gô lai"),
    ("go live", "gô lai"),
    ("go no-go", "gô nâu gâu"),
    ("go no go", "gô nâu gâu"),
    ("dry run", "đờ-rai răn"),
    ("audit log", "ô-đít lóc"),
    ("test case", "tét kêi"),
    ("test script", "tét sì-cờ-ríp"),
    ("test plan", "tét pờ-len"),
    ("test smoke", "tét sì-mốc"),
    ("smoke test", "sì-mốc tét"),
    ("worker retry", "uốc-cơ ri-trai"),
    ("duplicate callback", "đu-pli-kệt côn-béc"),
    ("user guide", "diu-dơ gai"),
    ("design freeze", "đi-zai phờ-ri"),
    ("build freeze", "biu phờ-ri"),
    ("merchant group", "mơ-chần gờ-rúp"),
    ("merchant pilot", "mơ-chần pai-lốt"),
    ("queue retry", "kiu ri-trai"),
    ("retry callback", "ri-trai côn-béc"),
    ("release checklist", "ri-lít chéc-lít"),
    ("go-live checklist", "gô lai chéc-lít"),
    ("rollback checklist", "rôn-béc chéc-lít"),
    ("training checklist", "tờ-rê-ninh chéc-lít"),
    ("rollback window", "rôn-béc uyn-đâu"),
    # single words
    ("ZenoPay", "Zeno Pay"),
    ("Nova", "Nô-va"),
    ("settlement", "sét-tồ-mừn"),
    ("deploy", "đi-ploi"),
    ("reconciliation", "ri-con-xi-li-ê-sần"),
    ("dashboard", "đát-boọc"),
    ("backend", "béc-en"),
    ("frontend", "phờ-ron-en"),
    ("canary", "ca-na-ri"),
    ("rollback", "rôn-béc"),
    ("rollout", "rô-lao"),
    ("idempotency", "ai-đêm-pô-ten-xi"),
    ("pilot", "pai-lốt"),
    ("merchant", "mơ-chần"),
    ("endpoint", "en-point"),
    ("summary", "sâm-mơ-ri"),
    ("schema", "sì-ki-ma"),
    ("callback", "côn-béc"),
    ("duplicate", "đu-pli-kệt"),
    ("latency", "lây-từn-xi"),
    ("severity", "sờ-ve-ri-ti"),
    ("timezone", "tai-dôn"),
    ("ledger", "le-jơ"),
    ("Slack", "sì-lác"),
    ("alert", "ơ-lớt"),
    ("queue", "kiu"),
    ("tooltip", "tun-típ"),
    ("monitoring", "mo-ni-tơ-rinh"),
    ("volume", "vo-lùm"),
    ("mapping", "máp-pinh"),
    ("baseline", "bây-sờ-lai"),
    ("regression", "ri-grét-sần"),
    ("retry", "ri-trai"),
    ("freeze", "phờ-ri"),
    ("optimize", "óp-ti-mai"),
    ("query", "qui-ri"),
    ("checklist", "chéc-lít"),
    ("friction", "phờ-ríc-sần"),
    ("portal", "po-tồ"),
    ("optional", "óp-sần-nồ"),
    ("mandatory", "men-đơ-tô-ri"),
    ("compliance", "com-pờ-lai-ần"),
    ("Compliance", "com-pờ-lai-ần"),
    ("Marketing", "ma-két-tinh"),
    ("marketing", "ma-két-tinh"),
    ("Support", "sơ-pót"),
    ("Tech", "téc"),
    ("hotline", "hót-lai"),
    ("script", "sì-cờ-ríp"),
    ("seed", "sít"),
    ("job", "jóp"),
    ("per", "pơ"),
    ("email", "i-meo"),
    ("bug", "bấc"),
    ("build", "biu"),
    ("view", "viu"),
    ("group", "gờ-rúp"),
    ("training", "tờ-rê-ninh"),
    ("wording", "uơ-đinh"),
    ("pending", "pen-đinh"),
    ("failed", "phây"),
    ("p95", "pi chín lăm"),
    ("p99", "pi chín chín"),
    ("UAT", "diu ây ti"),
    ("OTP", "ô tê pê"),
    ("QA", "kiu ây"),
    ("API", "ây pi ai"),
    ("RC", "a-xê"),
]

_PRONUNCIATION_RE = [
    (re.compile(r"(?<![0-9A-Za-zÀ-ỹ])" + re.escape(src) + r"(?![0-9A-Za-zÀ-ỹ])",
                re.IGNORECASE if src.islower() or not src[0].isupper() else 0),
     repl)
    for src, repl in PRONUNCIATION
]


def spoken(text: str) -> str:
    """Respell English/technical terms phonetically for the Vietnamese voices."""
    for pattern, repl in _PRONUNCIATION_RE:
        text = pattern.sub(repl, text)
    return text


def to_wav(mp3_path: Path, wav_path: Path) -> None:
    subprocess.run(
        [FFMPEG, "-y", "-i", str(mp3_path), "-vn",
         "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE),
         "-c:a", "pcm_s16le", str(wav_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def read_frames(wav_path: Path) -> bytes:
    with wave.open(str(wav_path), "rb") as src:
        return src.readframes(src.getnframes())


async def synth(text: str, cfg: dict, mp3_path: Path) -> None:
    last_exc: Exception | None = None
    for attempt in range(10):
        try:
            comm = edge_tts.Communicate(
                spoken(text), cfg["voice"], rate=cfg["rate"], pitch=cfg["pitch"]
            )
            await comm.save(str(mp3_path))
            if mp3_path.stat().st_size > 0:
                return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        await asyncio.sleep(min(2.0 * (attempt + 1), 12.0))
    raise RuntimeError(f"TTS failed after retries: {last_exc}")


def build(txt_path: Path) -> Path:
    content = txt_path.read_text(encoding="utf-8")
    turns = parse_dialogue(content)
    if not turns:
        raise SystemExit("No dialogue lines found.")

    pause = b"\x00" * int(PAUSE_SECONDS * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    output = bytearray()

    with tempfile.TemporaryDirectory(prefix="memoir-dialogue-") as tmp:
        tmpdir = Path(tmp)
        for i, (speaker, text) in enumerate(turns):
            cfg = SPEAKERS[speaker]
            mp3 = tmpdir / f"turn-{i:03d}.mp3"
            wav = tmpdir / f"turn-{i:03d}.wav"
            asyncio.run(synth(text, cfg, mp3))
            time.sleep(0.4)  # be gentle with the edge-tts endpoint
            to_wav(mp3, wav)
            output.extend(read_frames(wav))
            output.extend(pause)
            print(f"  [{i + 1:02d}/{len(turns)}] {speaker}: {text[:50]}...")

    wav_out = txt_path.with_suffix(".dialogue.wav")
    with wave.open(str(wav_out), "wb") as dst:
        dst.setnchannels(CHANNELS)
        dst.setsampwidth(SAMPLE_WIDTH)
        dst.setframerate(SAMPLE_RATE)
        dst.writeframes(bytes(output))

    mp3_out = txt_path.with_suffix(".dialogue.mp3")
    subprocess.run(
        [FFMPEG, "-y", "-i", str(wav_out), "-vn", "-ac", "2", "-ar", "44100",
         "-codec:a", "libmp3lame", "-b:a", "128k", "-id3v2_version", "3",
         str(mp3_out)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    wav_out.unlink(missing_ok=True)
    return mp3_out


def main() -> None:
    if len(sys.argv) > 1:
        txt_path = Path(sys.argv[1])
        if not txt_path.is_absolute():
            txt_path = OUT_DIR / txt_path
    else:
        txt_path = OUT_DIR / "2026-05-01 deploy ZenoPay Merchant Portal.txt"
    print(f"Building dialogue audio from: {txt_path.name}")
    out = build(txt_path)
    print(f"created {out.name}")


if __name__ == "__main__":
    main()
