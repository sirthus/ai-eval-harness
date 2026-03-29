"""Anthropic model adapter.

Reads ANTHROPIC_API_KEY from the environment.
Prompt template uses {requirement_id} and {requirement_text} placeholders.
Returns a validated ModelOutput or raises ValueError on parse failure.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic
from pydantic import ValidationError

from harness.schemas import ModelOutput

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(version: str) -> str:
    path = _PROMPTS_DIR / f"{version}.txt"
    return path.read_text(encoding="utf-8")


def generate(
    requirement_id: str,
    requirement_text: str,
    model_version: str,
    prompt_version: str,
) -> ModelOutput:
    """Call the model and return a validated ModelOutput."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    template = _load_prompt(prompt_version)
    user_message = template.format(
        requirement_id=requirement_id,
        requirement_text=requirement_text,
    )

    client = anthropic.Anthropic(api_key=api_key)
    logger.info("Generating output for %s with model %s", requirement_id, model_version)

    message = client.messages.create(
        model=model_version,
        max_tokens=2048,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = message.content[0].text.strip()
    logger.debug("Raw response for %s: %d chars", requirement_id, len(raw_text))

    return _parse_output(raw_text, requirement_id)


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
