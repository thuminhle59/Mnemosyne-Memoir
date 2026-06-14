"""Shared OpenAI-compatible client for GreenNode chat models."""
from openai import OpenAI
import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def chat(prompt: str, model: str, temperature: float = 0.2, max_tokens: int = 4096) -> str:
    """Single-turn chat; returns message.content text."""
    resp = client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""
