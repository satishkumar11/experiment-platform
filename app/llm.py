"""LLM-generated variant content.

Called only when an experiment is created (or edited), never from the /assign
hot path. If the call fails or no API key is configured, we fall back to a
static string so a flaky LLM never blocks experiment setup or breaks a page.
"""

import logging
import os

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        from anthropic import Anthropic

        _client = Anthropic(api_key=api_key)
    return _client


def generate_variant_content(prompt: str, fallback: str) -> str:
    client = _get_client()
    if client is None:
        logger.warning("ANTHROPIC_API_KEY not set, using fallback content")
        return fallback

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return text or fallback
    except Exception:
        logger.exception("LLM generation failed, using fallback content")
        return fallback
