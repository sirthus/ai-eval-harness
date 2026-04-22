"""Anthropic model adapter.

Reads ANTHROPIC_API_KEY from the environment (or .env file via dotenv).
Prompt template uses {requirement_id} and {requirement_text} placeholders.
Returns a validated ModelOutput or raises ValueError on parse failure.
Retries transient API errors up to 3 attempts with exponential backoff (1s, 2s, 4s).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - exercised only when dependency is absent
    def load_dotenv(*args, **kwargs) -> bool:
        return False

from harness.schemas import ModelOutput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = [1, 2, 4]


class ModelAPIError(Exception):
    """Raised when the model API fails after all retry attempts."""


def _get_anthropic_api_key() -> str:
    """Load dotenv lazily and return the Anthropic API key."""
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError("ANTHROPIC_API_KEY is not set")
    return api_key


def get_anthropic_client() -> anthropic.Anthropic:
    """Create and return an Anthropic client using the configured API key."""
    return anthropic.Anthropic(api_key=_get_anthropic_api_key())


def extract_text_content(message: Any, requirement_id: str, source: str) -> str:
    """Return the first non-empty text block from an Anthropic response."""
    content_blocks = getattr(message, "content", None)
    if not content_blocks:
        raise ValueError(
            f"{source} for {requirement_id} contained no content blocks"
        )

    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

    raise ValueError(
        f"{source} for {requirement_id} did not contain a text content block"
    )


def _load_prompt(version: str) -> str:
    path = _PROMPTS_DIR / f"{version}.txt"
    return path.read_text(encoding="utf-8")


def split_prompt(template: str) -> tuple[str, str]:
    """Split a prompt template on ### SYSTEM ### / ### USER ### markers.

    Returns (system_text, user_text). If markers are absent, returns ("", template)
    for backward compatibility with flat prompt files.
    """
    if "### SYSTEM ###" not in template or "### USER ###" not in template:
        return "", template
    after_system = template.split("### SYSTEM ###", 1)[1]
    system_part, user_part = after_system.split("### USER ###", 1)
    return system_part.strip(), user_part.strip()


def generate(
    requirement_id: str,
    requirement_text: str,
    model_version: str,
    prompt_version: str,
) -> ModelOutput:
    """Call the model and return a validated ModelOutput.

    Retries up to 3 times on transient API errors with exponential backoff.
    Raises ModelAPIError if all attempts fail.
    """
    template = _load_prompt(prompt_version)
    system_text, user_template = split_prompt(template)
    user_message = user_template.format(
        requirement_id=requirement_id,
        requirement_text=requirement_text,
    )

    client = get_anthropic_client()
    logger.info("Generating output for %s with model %s", requirement_id, model_version)

    create_kwargs: dict = dict(
        model=model_version,
        max_tokens=2048,
        messages=[{"role": "user", "content": user_message}],
    )
    if system_text:
        create_kwargs["system"] = system_text

    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            message = client.messages.create(**create_kwargs)
            raw_text = extract_text_content(
                message,
                requirement_id=requirement_id,
                source="Model response",
            )
            logger.debug("Raw response for %s: %d chars", requirement_id, len(raw_text))
            return _parse_output(raw_text, requirement_id)
        except anthropic.APIError as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                wait = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "API error for %s (attempt %d/%d), retrying in %ds: %s",
                    requirement_id, attempt + 1, _MAX_ATTEMPTS, wait, exc,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "API error for %s after %d attempts: %s",
                    requirement_id, _MAX_ATTEMPTS, exc,
                )

    raise ModelAPIError(
        f"Model API failed for {requirement_id} after {_MAX_ATTEMPTS} attempts"
    ) from last_exc


def _parse_output(raw_text: str, requirement_id: str) -> ModelOutput:
    """Parse raw model text into ModelOutput, raising ValueError on failure."""
    # Strip markdown code fences if the model added them despite instructions
    text = raw_text
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model output for {requirement_id} is not valid JSON: {exc}"
        ) from exc

    try:
        output = ModelOutput.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"Model output for {requirement_id} failed schema validation: {exc}"
        ) from exc

    return output
