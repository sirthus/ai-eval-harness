"""Focused tests for model adapter retries, lazy dotenv loading, and response parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from harness.model_adapter import (
    ModelAPIError,
    _get_anthropic_api_key,
    extract_text_content,
    generate,
)


def _api_error() -> anthropic.APIError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIError("API timeout", request, body=None)


def _mock_message(payload: dict | None = None) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock(text=json.dumps(payload or {
        "requirement_id": "REQ-001",
        "test_cases": [{
            "title": "Login succeeds",
            "preconditions": [],
            "steps": ["step"],
            "expected_result": "ok",
            "priority": "high",
            "type": "positive",
        }],
        "assumptions": [],
        "notes": "",
    }))]
    return message


def _message_with_content(*blocks) -> MagicMock:
    message = MagicMock()
    message.content = list(blocks)
    return message


class TestGetAnthropicApiKey:
    def test_loads_dotenv_lazily_before_lookup(self, mocker):
        def fake_load_dotenv() -> None:
            import os
            os.environ["ANTHROPIC_API_KEY"] = "loaded-from-dotenv"

        mocker.patch("harness.model_adapter.load_dotenv", side_effect=fake_load_dotenv)
        mocker.patch.dict("os.environ", {}, clear=True)

        assert _get_anthropic_api_key() == "loaded-from-dotenv"

    def test_raises_when_key_missing_after_dotenv(self, mocker):
        mocker.patch("harness.model_adapter.load_dotenv")
        mocker.patch.dict("os.environ", {}, clear=True)

        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY is not set"):
            _get_anthropic_api_key()


class TestExtractTextContent:
    def test_returns_first_non_empty_text_block(self):
        message = _message_with_content(
            type("Block", (), {"type": "text", "text": "   "})(),
            type("Block", (), {"type": "tool_use"})(),
            type("Block", (), {"type": "text", "text": "hello"})(),
        )

        assert extract_text_content(message, "REQ-001", "Model response") == "hello"

    def test_raises_on_empty_content(self):
        message = _message_with_content()

        with pytest.raises(ValueError, match="contained no content blocks"):
            extract_text_content(message, "REQ-001", "Model response")

    def test_raises_when_no_text_blocks_exist(self):
        message = _message_with_content(type("Block", (), {"type": "tool_use"})())

        with pytest.raises(ValueError, match="did not contain a text content block"):
            extract_text_content(message, "REQ-001", "Model response")


class TestGenerateRetries:
    def test_raises_model_api_error_after_exhausted_retries(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [_api_error(), _api_error(), _api_error()]
        anthropic_ctor = mocker.patch("harness.model_adapter.anthropic.Anthropic", return_value=mock_client)
        sleep = mocker.patch("harness.model_adapter.time.sleep")
        mocker.patch(
            "harness.model_adapter._load_prompt",
            return_value="Requirement: {requirement_id}\nText: {requirement_text}",
        )
        mocker.patch("harness.model_adapter._get_anthropic_api_key", return_value="test-key")

        with pytest.raises(ModelAPIError, match="after 3 attempts"):
            generate("REQ-001", "Users can log in.", "claude-sonnet-4-6", "v2")

        assert anthropic_ctor.call_count == 1
        assert mock_client.messages.create.call_count == 3
        assert sleep.call_args_list == [mocker.call(1), mocker.call(2)]

    def test_retries_once_then_succeeds_without_extra_attempts(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [_api_error(), _mock_message()]
        mocker.patch("harness.model_adapter.anthropic.Anthropic", return_value=mock_client)
        sleep = mocker.patch("harness.model_adapter.time.sleep")
        mocker.patch(
            "harness.model_adapter._load_prompt",
            return_value="Requirement: {requirement_id}\nText: {requirement_text}",
        )
        mocker.patch("harness.model_adapter._get_anthropic_api_key", return_value="test-key")

        output = generate("REQ-001", "Users can log in.", "claude-sonnet-4-6", "v2")

        assert output.requirement_id == "REQ-001"
        assert mock_client.messages.create.call_count == 2
        assert sleep.call_args_list == [mocker.call(1)]

    def test_empty_content_raises_value_error_without_retry(self, mocker):
        message = _message_with_content()
        mock_client = MagicMock()
        mock_client.messages.create.return_value = message
        mocker.patch("harness.model_adapter.anthropic.Anthropic", return_value=mock_client)
        sleep = mocker.patch("harness.model_adapter.time.sleep")
        mocker.patch(
            "harness.model_adapter._load_prompt",
            return_value="Requirement: {requirement_id}\nText: {requirement_text}",
        )
        mocker.patch("harness.model_adapter._get_anthropic_api_key", return_value="test-key")

        with pytest.raises(ValueError, match="contained no content blocks"):
            generate("REQ-001", "Users can log in.", "claude-sonnet-4-6", "v2")

        assert mock_client.messages.create.call_count == 1
        sleep.assert_not_called()

    def test_non_text_content_raises_value_error_without_retry(self, mocker):
        message = _message_with_content(type("Block", (), {"type": "tool_use"})())
        mock_client = MagicMock()
        mock_client.messages.create.return_value = message
        mocker.patch("harness.model_adapter.anthropic.Anthropic", return_value=mock_client)
        sleep = mocker.patch("harness.model_adapter.time.sleep")
        mocker.patch(
            "harness.model_adapter._load_prompt",
            return_value="Requirement: {requirement_id}\nText: {requirement_text}",
        )
        mocker.patch("harness.model_adapter._get_anthropic_api_key", return_value="test-key")

        with pytest.raises(ValueError, match="did not contain a text content block"):
            generate("REQ-001", "Users can log in.", "claude-sonnet-4-6", "v2")

        assert mock_client.messages.create.call_count == 1
        sleep.assert_not_called()
