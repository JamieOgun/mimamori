"""Shared AI& inference client for the scoring pipeline.

AI& (https://aiand.com) serves open models behind an OpenAI-compatible API, so
we reuse the ``openai`` SDK and simply repoint it at the AI& base URL. The
individual scorers (``deepseek``, ``glm``, ``qwen_scorer``) import
``get_client`` from here instead of constructing their own client, keeping the
base URL and credentials in one place.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from mimamori import config

logger = logging.getLogger(__name__)

# Cached singleton; creating the client sets up a connection pool we want to
# reuse across scoring calls rather than rebuild each time.
_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Return the shared AI& inference client, creating it on first use.

    Returns:
        An ``AsyncOpenAI`` instance configured for the AI& endpoint.

    Raises:
        RuntimeError: If ``AIAND_API_KEY`` is not set in the environment.
    """
    global _client
    if _client is None:
        config.require("AIAND_API_KEY")
        logger.debug("Creating AI& client for base_url=%s", config.AIAND_BASE_URL)
        _client = AsyncOpenAI(
            base_url=config.AIAND_BASE_URL,
            api_key=config.AIAND_API_KEY,
        )
    return _client


async def complete(
    prompt: str,
    *,
    model: str | None = None,
    **kwargs: object,
) -> str:
    """Run a single-turn chat completion against AI& and return the text.

    Args:
        prompt: The user message to send.
        model: Model id to use; defaults to ``config.AIAND_MODEL``.
        **kwargs: Extra arguments forwarded to ``chat.completions.create``
            (e.g. ``temperature``, ``max_tokens``, ``response_format``).

    Returns:
        The assistant message content (empty string if the model returns none).
    """
    response = await get_client().chat.completions.create(
        model=model or config.AIAND_MODEL,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    return response.choices[0].message.content or ""
