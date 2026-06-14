"""Local recorder: capture Teams audio via ffmpeg+BlackHole, then upload to the agent.

Setup (macOS, one-time):
  1. Install BlackHole 2ch + ffmpeg (brew install blackhole-2ch ffmpeg).
  2. Create a Multi-Output Device (BlackHole + your speakers) so you still hear the call.
  3. In Teams, keep default mic; system audio is routed through BlackHole for capture.

Usage:
  python -m recorder.record --device ":BlackHole 2ch" --agent-url <URL> --format docx --title "Họp X"
  (Ctrl-C to stop recording -> uploads automatically.)
"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
import urllib.request


def build_payload(audio_bytes: bytes, fmt: str, title: str | None, date: str | None) -> dict:
    p = {"audio_base64": base64.b64encode(audio_bytes).decode(), "format": fmt}
    if title:
        p["meeting_title"] = title
    if date:
        p["date"] = date
    return p


def post(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


def capture(device: str, out_path: str) -> None:
    """Record from an avfoundation audio device until Ctrl-C (ffmpeg)."""
    cmd = ["ffmpeg", "-y", "-f", "avfoundation", "-i", device,
           "-ac", "1", "-ar", "16000", out_path]
    print("Recording... press Ctrl-C to stop.")
    proc = subprocess.Popen(cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=":BlackHole 2ch")
    ap.add_argument("--agent-url", required=True)
    ap.add_argument("--format", default="docx", choices=["docx", "pdf"])
    ap.add_argument("--title")
    ap.add_argument("--date")
    ap.add_argument("--token")
    args = ap.parse_args(argv)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    capture(args.device, wav)
    audio = open(wav, "rb").read()
    print(f"Captured {len(audio)} bytes, uploading...")
    out = post(args.agent_url, build_payload(audio, args.format, args.title, args.date), args.token)
    if out.get("status") == "success":
        fname = out["report_filename"]
        open(fname, "wb").write(base64.b64decode(out["report_base64"]))
        print(f"Saved report: {fname}  (email_sent={out.get('email_sent')})")
        return 0
    print("Agent error:", out.get("message"), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
