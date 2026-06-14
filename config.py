"""Central config: endpoints, model paths, SMTP. All via env (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1")
STT_URL = os.getenv(
    "STT_URL",
    "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/maas/user-111659/openai/whisper-large-v3/v1/audio/transcriptions",
)

# --- Models (all overridable via env; locked in after plan per design) ---
# Extraction tier: transcript -> MeetingReport + KnowledgeFact[] (runs every ingest,
# needs reliable JSON). Safe default = minimax (E2E verified in Meeting Ghost).
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "minimax/minimax-m2.5")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", SUMMARY_MODEL)
# Heavy reasoning tier: Q&A multi-source, contradiction, digest.
# gemma won the A/B (same quality as qwen, far faster, reliable on this key);
# gemini/gpt return 404 on this key, so they are NOT defaults.
REASONING_MODEL = os.getenv("REASONING_MODEL", "google/gemma-4-31b-it")

# Per-tier fallbacks (used only when the primary model errors/404s):
#   extraction -> gemma (fast, reliable); reasoning -> qwen (quality, but slow).
EXTRACT_FALLBACK_MODEL = os.getenv("EXTRACT_FALLBACK_MODEL", "google/gemma-4-31b-it")
REASONING_FALLBACK_MODEL = os.getenv("REASONING_FALLBACK_MODEL", "qwen/qwen3-5-27b")
STT_MODEL = os.getenv("STT_MODEL", "openai/whisper-large-v3")

# Above this many characters of transcript, switch from 1-pass to map-reduce.
MAP_REDUCE_CHAR_THRESHOLD = int(os.getenv("MAP_REDUCE_CHAR_THRESHOLD", "24000"))

# Long audio is split into WAV chunks of this many seconds before STT (endpoint
# only accepts WAV and large/long files time out). 600s mono16k ≈ 19 MB/chunk.
STT_CHUNK_SEC = int(os.getenv("STT_CHUNK_SEC", "600"))

# Whisper prompt biasing: this managed endpoint ignores it as a glossary and can
# even add hallucinations, so it's OFF by default. Term fixing is done in
# post-processing (STT_CORRECTIONS) instead, which is deterministic.
STT_PROMPT = os.getenv("STT_PROMPT", "")

# ---- STT term correction (3 layers; judges may upload audio on ANY topic) ----
# Whisper mishears domain proper nouns ("Claw-a-thon" -> "CloudTown/Glow Tone").
# Each pair is [regex, replacement], applied case-insensitively.
import json as _json


def _env_pairs(name: str, default: list) -> list:
    try:
        return _json.loads(os.getenv(name)) if os.getenv(name) else default
    except Exception:  # noqa: BLE001 - bad env JSON -> defaults
        return default


# Layer 1 — NORMALIZE: maps a term to its canonical spelling (same concept).
# Always on; safe even if the original wasn't "wrong" (just standardizes).
STT_NORMALIZE = _env_pairs("STT_NORMALIZE", [
    [r"\bza+lo[\s-]?pay\b", "ZaloPay"],
    [r"\bagent[\s-]?base\b", "AgentBase"],
    [r"\bgreen[\s-]?node\b", "GreenNode"],
    [r"\bopen[\s-]?claw\b", "OpenClaw"],
])

# Layer 2 — TERM FIXES: maps a mis-heard word to a proper noun (different word).
# Risky on unknown-topic audio (e.g. a real "GlowTone" brand) -> behind a flag.
STT_FIX_TERMS = os.getenv("STT_FIX_TERMS", "true").lower() == "true"
STT_TERM_FIXES = _env_pairs("STT_TERM_FIXES", [
    [r"\bcloud[\s-]?(thorn|town|thon|tron)\b", "Claw-a-thon"],
    [r"\bglow[\s-]?tone\b", "Claw-a-thon"],
    [r"\bclaw[\s-]?a[\s-]?thon\b", "Claw-a-thon"],
    [r"\bcl[ao]w[\s-]?a[\s-]?thon\b", "Claw-a-thon"],
])

# Layer 3 — LLM correction: context-aware fix of mis-transcribed proper nouns
# against a glossary; leaves unrelated audio untouched. Best for unknown topics.
STT_LLM_CORRECT = os.getenv("STT_LLM_CORRECT", "true").lower() == "true"
STT_CORRECT_MODEL = os.getenv("STT_CORRECT_MODEL", "google/gemma-4-31b-it")
STT_GLOSSARY = os.getenv(
    "STT_GLOSSARY",
    "Claw-a-thon, GreenNode, ZaloPay, AgentBase, OpenClaw, Mnemosyne",
)

# --- Memory store (SQLAlchemy; SQLite local for demo, Postgres via env later) ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///mnemosyne.db")

# Email (optional)
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)
EMAIL_TO = [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()]
