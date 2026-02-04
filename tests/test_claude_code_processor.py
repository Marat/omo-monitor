"""Tests for Claude Code processor."""

import json
import tempfile
from pathlib import Path

import pytest

from omo_monitor.utils.claude_code_processor import (
    ClaudeCodeProcessor,
    infer_provider_from_model,
    normalize_claude_model_name,
)


class TestInferProvider:
    """Tests for provider inference from model name."""

    def test_claude_models(self):
        assert infer_provider_from_model("claude-opus-4-5-20251101") == "anthropic"
        assert infer_provider_from_model("claude-sonnet-4-20250514") == "anthropic"
        assert infer_provider_from_model("claude-haiku-3.5") == "anthropic"

    def test_openai_models(self):
        assert infer_provider_from_model("gpt-4o") == "openai"
        assert infer_provider_from_model("gpt-5-1") == "openai"
        assert infer_provider_from_model("o1-preview") == "openai"
        assert infer_provider_from_model("o3-mini") == "openai"

    def test_google_models(self):
        assert infer_provider_from_model("gemini-3-pro") == "google"
        assert infer_provider_from_model("gemini-2.0-flash") == "google"

    def test_unknown_models(self):
        assert infer_provider_from_model("unknown-model") == "unknown"
        assert infer_provider_from_model("custom-llm") == "unknown"


class TestNormalizeModelName:
    """Tests for model name normalization."""

    def test_claude_with_date_suffix(self):
        assert normalize_claude_model_name("claude-opus-4-5-20251101") == "claude-opus-4.5"
        assert normalize_claude_model_name("claude-sonnet-4-20250514") == "claude-sonnet-4"

    def test_claude_without_date(self):
        assert normalize_claude_model_name("claude-opus-4-5") == "claude-opus-4.5"
        assert normalize_claude_model_name("claude-haiku-3-5") == "claude-haiku-3.5"

    def test_lowercase_conversion(self):
        assert normalize_claude_model_name("Claude-Opus-4-5") == "claude-opus-4.5"


class TestClaudeCodeProcessor:
    """Tests for ClaudeCodeProcessor class."""

    def test_parse_jsonl_file(self, tmp_path):
        """Test parsing a JSONL file."""
        # Create test JSONL file
        jsonl_file = tmp_path / "test.jsonl"
        records = [
            {"type": "user", "uuid": "1"},
            {"type": "assistant", "uuid": "2", "message": {"usage": {"input_tokens": 10}}},
        ]
        jsonl_file.write_text("\n".join(json.dumps(r) for r in records))

        # Parse the file
        result = ClaudeCodeProcessor.parse_jsonl_file(jsonl_file)

        assert len(result) == 2
        assert result[0]["type"] == "user"
        assert result[1]["type"] == "assistant"

    def test_parse_jsonl_file_with_empty_lines(self, tmp_path):
        """Test parsing JSONL with empty lines."""
        jsonl_file = tmp_path / "test.jsonl"
        content = '{"type": "user"}\n\n{"type": "assistant"}\n'
        jsonl_file.write_text(content)

        result = ClaudeCodeProcessor.parse_jsonl_file(jsonl_file)
        assert len(result) == 2

    def test_parse_jsonl_file_with_malformed_lines(self, tmp_path):
        """Test parsing JSONL with malformed JSON."""
        jsonl_file = tmp_path / "test.jsonl"
        content = '{"type": "user"}\nnot json\n{"type": "assistant"}\n'
        jsonl_file.write_text(content)

        result = ClaudeCodeProcessor.parse_jsonl_file(jsonl_file)
        # Should skip the malformed line
        assert len(result) == 2

    def test_extract_assistant_messages(self):
        """Test filtering to assistant messages with usage."""
        records = [
            {"type": "user", "uuid": "1"},
            {"type": "assistant", "uuid": "2", "message": {"usage": {"input_tokens": 10}}},
            {"type": "assistant", "uuid": "3", "message": {}},  # No usage
            {"type": "assistant", "uuid": "4", "message": {"usage": {"input_tokens": 5, "output_tokens": 3}}},
        ]

        result = ClaudeCodeProcessor.extract_assistant_messages(records)

        assert len(result) == 2
        assert result[0]["uuid"] == "2"
        assert result[1]["uuid"] == "4"

    def test_map_to_interaction_file(self, tmp_path):
        """Test mapping Claude Code record to InteractionFile."""
        record = {
            "sessionId": "test-session",
            "type": "assistant",
            "uuid": "msg-123",
            "parentUuid": "msg-122",
            "timestamp": "2026-02-02T18:14:51.091Z",
            "cwd": "/home/user/project",
            "message": {
                "model": "claude-opus-4-5-20251101",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 500,
                },
                "stop_reason": "end_turn",
            },
        }

        file_path = tmp_path / "test.jsonl"
        result = ClaudeCodeProcessor.map_to_interaction_file(record, "test-session", file_path)

        assert result is not None
        assert result.session_id == "test-session"
        assert result.message_id == "msg-123"
        assert result.parent_id == "msg-122"
        assert result.model_id == "claude-opus-4.5"
        assert result.provider_id == "anthropic"
        assert result.tokens.input == 100
        assert result.tokens.output == 50
        assert result.tokens.cache_write == 1000
        assert result.tokens.cache_read == 500
        assert result.project_path == "/home/user/project"
        assert result.role == "assistant"

    def test_load_session_data(self, tmp_path):
        """Test loading complete session from JSONL file."""
        # Create test JSONL file
        jsonl_file = tmp_path / "test-session.jsonl"
        records = [
            {
                "sessionId": "test-session",
                "type": "user",
                "uuid": "1",
            },
            {
                "sessionId": "test-session",
                "type": "assistant",
                "uuid": "2",
                "parentUuid": "1",
                "timestamp": "2026-02-02T18:14:51.091Z",
                "cwd": "/home/user/project",
                "message": {
                    "model": "claude-opus-4.5",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                    },
                },
            },
        ]
        jsonl_file.write_text("\n".join(json.dumps(r) for r in records))

        session = ClaudeCodeProcessor.load_session_data(jsonl_file)

        assert session is not None
        assert session.session_id == "test-session"
        assert len(session.files) == 1  # Only assistant with usage
        assert session.files[0].tokens.total == 150

    def test_has_data_empty_dir(self, tmp_path):
        """Test has_data returns False for empty directory."""
        assert ClaudeCodeProcessor.has_data(str(tmp_path)) is False

    def test_has_data_with_files(self, tmp_path):
        """Test has_data returns True when JSONL files exist."""
        jsonl_file = tmp_path / "session.jsonl"
        jsonl_file.write_text('{"type": "user"}')

        assert ClaudeCodeProcessor.has_data(str(tmp_path)) is True
