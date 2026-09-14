"""Drafting engine: turns signals into a post draft.

Uses the OpenAI API when OPENAI_API_KEY is set; otherwise falls back to a
deterministic template so the PoC works end-to-end without any LLM key.
"""
import requests

from app.config.settings import OPENAI_API_KEY, OPENAI_MODEL

SYSTEM_PROMPT = """You create LinkedIn posts for software engineers.

Write a concise post (maximum 150 words) in first person describing the work
provided in the context below.

Focus on:
- What the project is about
- Core skills covered
- What was learned
- Next steps

Use a few relevant emojis to keep it lively. Return ONLY the post text —
no headings, no formatting, no explanations."""


def _draft_with_llm(context: str) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Context:\n\n{context}\n\nCreate the post."},
            ],
            "max_tokens": 400,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _draft_with_template(signals: list[dict]) -> str:
    titles = [s["title"] for s in signals][:5]
    bullets = "\n".join(f"• {t}" for t in titles)
    return (
        "🚀 Recent progress update:\n\n"
        f"{bullets}\n\n"
        "Learned a lot along the way — more improvements coming soon. "
        "#buildinpublic #softwareengineering"
    )


def draft_post(signals: list[dict]) -> str:
    """Draft one post from a list of signal dicts (title/content/source/url).

    Uses the LLM when a key is configured; on any LLM/API failure falls back
    to the deterministic template so drafting never blocks the pipeline.
    """
    if not signals:
        raise ValueError("No signals provided for drafting.")
    if OPENAI_API_KEY:
        context = "\n\n---\n\n".join(
            f"[{s['source']}/{s['type']}] {s['title']}\n{s.get('content', '')[:1000]}"
            for s in signals
        )
        try:
            return _draft_with_llm(context)
        except requests.RequestException as e:
            detail = ""
            if getattr(e, "response", None) is not None:
                detail = f" ({e.response.status_code}: {e.response.text[:200]})"
            print(f"⚠ LLM drafting failed{detail}. Check your OPENAI_API_KEY "
                  "quota/billing. Falling back to template draft.")
    return _draft_with_template(signals)
