"""Claude Code log processor for OmO-monitor.

Handles parsing and processing of Claude Code JSONL session logs.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Generator
from datetime import datetime

from ..models.session import (
    SessionData,
    InteractionFile,
    TokenUsage,
    TimeData,
)


def infer_provider_from_model(model_id: str) -> str:
    """Infer provider ID from model name.

    Args:
        model_id: Model identifier (e.g., claude-opus-4-5-20251101)

    Returns:
        Provider ID (anthropic, openai, google, unknown)
    """
    model_lower = model_id.lower()

    if model_lower.startswith("claude"):
        return "anthropic"
    if model_lower.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    if model_lower.startswith("gemini"):
        return "google"
    if model_lower.startswith("deepseek"):
        return "deepseek"
    if model_lower.startswith("qwen"):
        return "alibaba"
    if model_lower.startswith("mistral"):
        return "mistral"

    return "unknown"


def normalize_claude_model_name(model_id: str) -> str:
    """Normalize Claude Code model name for pricing lookup.

    Handles formats like: claude-opus-4-5-20251101 -> claude-opus-4.5

    Args:
        model_id: Raw model ID from Claude Code

    Returns:
        Normalized model name
    """
    model_id = model_id.lower()

    # Strip date suffixes like -20250514, -20251101
    model_id = re.sub(r"-\d{8}$", "", model_id)

    # Normalize version separators: claude-opus-4-5 -> claude-opus-4.5
    model_id = re.sub(
        r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)", r"claude-\1-\2.\3", model_id
    )

    return model_id


class ClaudeCodeProcessor:
    """Handles Claude Code JSONL log files."""

    @staticmethod
    def get_claude_code_storage_path() -> Optional[Path]:
        """Get Claude Code projects directory.

        Returns:
            Path to Claude Code projects directory or None if not found
        """
        # Try to get from configuration first
        try:
            from ..config import config_manager

            storage_path = Path(config_manager.config.paths.claude_code_storage_dir)
            if storage_path.exists():
                return storage_path
        except ImportError:
            pass

        # Standard Claude Code storage location as fallback
        home = Path.home()
        storage_path = home / ".claude" / "projects"

        if storage_path.exists():
            return storage_path

        return None

    @staticmethod
    def find_session_files(base_path: Optional[str] = None) -> List[Path]:
        """Find all JSONL session files in Claude Code projects.

        Args:
            base_path: Override base path (defaults to Claude Code projects dir)

        Returns:
            List of JSONL file paths sorted by modification time (newest first)
        """
        if base_path:
            base_dir = Path(base_path).expanduser()
        else:
            base_dir = ClaudeCodeProcessor.get_claude_code_storage_path()

        if not base_dir or not base_dir.exists():
            return []

        # Find all .jsonl files in project directories
        jsonl_files = list(base_dir.glob("**/*.jsonl"))

        # Sort by modification time (most recent first)
        jsonl_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return jsonl_files

    @staticmethod
    def parse_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
        """Parse JSONL file, return list of records.

        Args:
            file_path: Path to JSONL file

        Returns:
            List of parsed JSON records
        """
        records = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        records.append(record)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue
        except (FileNotFoundError, PermissionError, UnicodeDecodeError):
            return []

        return records

    @staticmethod
    def extract_assistant_messages(records: List[Dict]) -> List[Dict]:
        """Filter records to only assistant messages with usage data.

        Args:
            records: List of Claude Code records

        Returns:
            List of assistant records that have token usage
        """
        assistant_records = []

        for record in records:
            # Only process assistant messages
            if record.get("type") != "assistant":
                continue

            # Must have message with usage data
            message = record.get("message", {})
            usage = message.get("usage", {})

            # Skip if no token data
            if not usage.get("input_tokens") and not usage.get("output_tokens"):
                continue

            assistant_records.append(record)

        return assistant_records

    @staticmethod
    def map_to_interaction_file(
        record: Dict,
        session_id: str,
        file_path: Path,
    ) -> Optional[InteractionFile]:
        """Map Claude Code record to InteractionFile.

        Args:
            record: Claude Code JSON record
            session_id: Session ID (from sessionId field)
            file_path: Source file path

        Returns:
            InteractionFile object or None if mapping failed
        """
        try:
            # Extract message data
            message = record.get("message", {})
            usage = message.get("usage", {})

            # Model info
            model_id_raw = message.get("model", "unknown")
            model_id = normalize_claude_model_name(model_id_raw)
            provider_id = infer_provider_from_model(model_id_raw)

            # Token usage
            tokens = TokenUsage(
                input=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
                cache_write=usage.get("cache_creation_input_tokens", 0),
                cache_read=usage.get("cache_read_input_tokens", 0),
                reasoning=0,  # Claude Code doesn't expose reasoning tokens separately
            )

            # Time data
            time_data = None
            timestamp_str = record.get("timestamp")
            if timestamp_str:
                try:
                    # Parse ISO format: 2026-02-02T18:14:51.091Z
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    created_ms = int(dt.timestamp() * 1000)
                    time_data = TimeData(created=created_ms)
                except (ValueError, AttributeError):
                    pass

            # Project path
            project_path = record.get("cwd")

            # Role - Claude Code uses "type" field
            role = "assistant" if record.get("type") == "assistant" else "user"

            return InteractionFile(
                file_path=file_path,
                session_id=session_id,
                message_id=record.get("uuid"),
                role=role,
                parent_id=record.get("parentUuid"),
                model_id=model_id,
                model_id_raw=model_id_raw,
                provider_id=provider_id,
                tokens=tokens,
                time_data=time_data,
                cost=None,  # Claude Code doesn't report cost
                agent=None,  # Claude Code doesn't have agents
                mode=None,
                category=None,
                skills=[],
                project_path=project_path,
                root_path=None,
                finish_reason=message.get("stop_reason"),
                summary=None,
                system_prompt=None,
                tools_config=None,
                raw_data=record,
            )

        except (KeyError, ValueError, TypeError):
            return None

    @staticmethod
    def load_session_data(session_path: Path) -> Optional[SessionData]:
        """Load complete session from JSONL file.

        Args:
            session_path: Path to JSONL session file

        Returns:
            SessionData object or None if loading failed
        """
        try:
            if not session_path.exists() or not session_path.suffix == ".jsonl":
                return None

            records = ClaudeCodeProcessor.parse_jsonl_file(session_path)
            if not records:
                return None

            # Get session ID from first record
            session_id = None
            for record in records:
                if record.get("sessionId"):
                    session_id = record["sessionId"]
                    break

            if not session_id:
                # Use filename as session ID fallback
                session_id = session_path.stem

            # Filter to assistant messages with usage
            assistant_records = ClaudeCodeProcessor.extract_assistant_messages(records)

            # Map to InteractionFile objects
            interaction_files = []
            for record in assistant_records:
                interaction = ClaudeCodeProcessor.map_to_interaction_file(
                    record, session_id, session_path
                )
                if interaction and interaction.tokens.total > 0:
                    interaction_files.append(interaction)

            if not interaction_files:
                return None

            # Extract session title from first user message if available
            session_title = None
            for record in records:
                if record.get("type") == "summary":
                    session_title = record.get("summary")
                    break

            return SessionData(
                session_id=session_id,
                session_path=session_path,
                files=interaction_files,
                session_title=session_title,
            )

        except Exception:
            return None

    @staticmethod
    def load_all_sessions(
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        """Load all sessions from Claude Code projects.

        Args:
            base_path: Override base path (defaults to Claude Code projects dir)
            limit: Maximum number of sessions to load (None for all)

        Returns:
            List of SessionData objects sorted by start time (newest first)
        """
        session_files = ClaudeCodeProcessor.find_session_files(base_path)

        if limit:
            session_files = session_files[:limit]

        sessions = []
        for session_file in session_files:
            session_data = ClaudeCodeProcessor.load_session_data(session_file)
            if session_data:
                sessions.append(session_data)

        # Sort by start time (newest first)
        sessions.sort(
            key=lambda s: s.start_time or datetime.min,
            reverse=True,
        )

        return sessions

    @staticmethod
    def session_generator(
        base_path: Optional[str] = None,
    ) -> Generator[SessionData, None, None]:
        """Generator that yields sessions one by one (memory efficient).

        Args:
            base_path: Override base path (defaults to Claude Code projects dir)

        Yields:
            SessionData objects
        """
        session_files = ClaudeCodeProcessor.find_session_files(base_path)

        for session_file in session_files:
            session_data = ClaudeCodeProcessor.load_session_data(session_file)
            if session_data:
                yield session_data

    @staticmethod
    def has_data(base_path: Optional[str] = None) -> bool:
        """Check if Claude Code has any session data.

        Args:
            base_path: Override base path

        Returns:
            True if there are JSONL files, False otherwise
        """
        session_files = ClaudeCodeProcessor.find_session_files(base_path)
        return len(session_files) > 0
