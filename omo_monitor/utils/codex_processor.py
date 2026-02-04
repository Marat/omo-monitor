"""Codex CLI log processor for OmO-monitor.

Handles parsing and processing of Codex JSONL session logs.
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


def infer_provider_from_codex_model(model_id: str) -> str:
    """Infer provider ID from Codex model name.

    Args:
        model_id: Model identifier

    Returns:
        Provider ID
    """
    model_lower = model_id.lower()

    if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
        return "openai"
    if "claude" in model_lower:
        return "anthropic"
    if "gemini" in model_lower:
        return "google"

    return "openai"  # Default for Codex


class CodexProcessor:
    """Handles Codex CLI JSONL log files."""

    @staticmethod
    def get_codex_storage_path() -> Optional[Path]:
        """Get Codex sessions directory.

        Returns:
            Path to Codex sessions directory or None if not found
        """
        home = Path.home()
        storage_path = home / ".codex" / "sessions"

        if storage_path.exists():
            return storage_path

        return None

    @staticmethod
    def find_session_files(base_path: Optional[str] = None) -> List[Path]:
        """Find all JSONL session files in Codex sessions.

        Args:
            base_path: Override base path (defaults to Codex sessions dir)

        Returns:
            List of JSONL file paths sorted by modification time (newest first)
        """
        if base_path:
            base_dir = Path(base_path).expanduser()
        else:
            base_dir = CodexProcessor.get_codex_storage_path()

        if not base_dir or not base_dir.exists():
            return []

        # Find all rollout-*.jsonl files
        jsonl_files = list(base_dir.glob("**/rollout-*.jsonl"))

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
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        records.append(record)
                    except json.JSONDecodeError:
                        continue
        except (FileNotFoundError, PermissionError, UnicodeDecodeError):
            return []

        return records

    @staticmethod
    def extract_token_events(records: List[Dict]) -> List[Dict]:
        """Filter records to token_count events with usage data.

        Args:
            records: List of Codex records

        Returns:
            List of token_count event records
        """
        token_records = []

        for record in records:
            if record.get("type") != "event_msg":
                continue

            payload = record.get("payload") or {}
            if payload.get("type") != "token_count":
                continue

            info = payload.get("info") or {}
            usage = info.get("total_token_usage") or {}

            if not usage.get("input_tokens") and not usage.get("output_tokens"):
                continue

            token_records.append(record)

        return token_records

    @staticmethod
    def extract_session_meta(records: List[Dict]) -> Optional[Dict]:
        """Extract session metadata from records.

        Args:
            records: List of Codex records

        Returns:
            Session meta record or None
        """
        for record in records:
            if record.get("type") == "session_meta":
                return record.get("payload", {})
        return None

    @staticmethod
    def map_to_interaction_file(
        record: Dict,
        session_id: str,
        file_path: Path,
        model_id: str = "gpt-5",
    ) -> Optional[InteractionFile]:
        """Map Codex token_count record to InteractionFile.

        Args:
            record: Codex JSON record
            session_id: Session ID
            file_path: Source file path
            model_id: Model ID from session meta

        Returns:
            InteractionFile object or None if mapping failed
        """
        try:
            payload = record.get("payload", {})
            info = payload.get("info", {})
            usage = info.get("total_token_usage", {})

            # Token usage
            tokens = TokenUsage(
                input=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
                cache_write=0,  # Codex doesn't differentiate cache write
                cache_read=usage.get("cached_input_tokens", 0),
                reasoning=usage.get("reasoning_output_tokens", 0),
            )

            # Time data
            time_data = None
            timestamp_str = record.get("timestamp")
            if timestamp_str:
                try:
                    dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    created_ms = int(dt.timestamp() * 1000)
                    time_data = TimeData(created=created_ms)
                except (ValueError, AttributeError):
                    pass

            provider_id = infer_provider_from_codex_model(model_id)

            return InteractionFile(
                file_path=file_path,
                session_id=session_id,
                message_id=None,
                role="assistant",
                parent_id=None,
                model_id=model_id,
                model_id_raw=model_id,
                provider_id=provider_id,
                tokens=tokens,
                time_data=time_data,
                cost=None,
                agent=None,
                mode=None,
                category=None,
                skills=[],
                project_path=None,
                root_path=None,
                finish_reason=None,
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

            records = CodexProcessor.parse_jsonl_file(session_path)
            if not records:
                return None

            # Extract session metadata
            meta = CodexProcessor.extract_session_meta(records)
            session_id = meta.get("id") if meta else session_path.stem

            # Get model from session meta
            model_id = "gpt-5"  # Default for Codex
            if meta and meta.get("model_provider"):
                provider = meta.get("model_provider", "openai")
                if provider == "openai":
                    model_id = "gpt-5"
                elif provider == "anthropic":
                    model_id = "claude-sonnet-4"

            # Get project path from meta
            project_path = meta.get("cwd") if meta else None

            # Extract token events
            token_records = CodexProcessor.extract_token_events(records)

            # Map to InteractionFile objects - use incremental tokens
            interaction_files = []
            prev_input = 0
            prev_output = 0
            prev_cached = 0
            prev_reasoning = 0

            for record in token_records:
                payload = record.get("payload", {})
                info = payload.get("info", {})
                usage = info.get("total_token_usage", {})

                # Calculate incremental tokens
                curr_input = usage.get("input_tokens", 0)
                curr_output = usage.get("output_tokens", 0)
                curr_cached = usage.get("cached_input_tokens", 0)
                curr_reasoning = usage.get("reasoning_output_tokens", 0)

                incr_input = max(0, curr_input - prev_input)
                incr_output = max(0, curr_output - prev_output)
                incr_cached = max(0, curr_cached - prev_cached)
                incr_reasoning = max(0, curr_reasoning - prev_reasoning)

                # Skip if no new tokens
                if incr_input == 0 and incr_output == 0:
                    prev_input = curr_input
                    prev_output = curr_output
                    prev_cached = curr_cached
                    prev_reasoning = curr_reasoning
                    continue

                # Create modified record with incremental tokens
                incr_record = dict(record)
                incr_record["_incremental"] = {
                    "input_tokens": incr_input,
                    "output_tokens": incr_output,
                    "cached_input_tokens": incr_cached,
                    "reasoning_output_tokens": incr_reasoning,
                }

                interaction = CodexProcessor.map_to_interaction_file(
                    record, session_id, session_path, model_id
                )
                if interaction:
                    # Override with incremental tokens
                    interaction.tokens = TokenUsage(
                        input=incr_input,
                        output=incr_output,
                        cache_write=0,
                        cache_read=incr_cached,
                        reasoning=incr_reasoning,
                    )
                    if project_path:
                        interaction.project_path = project_path
                    interaction_files.append(interaction)

                prev_input = curr_input
                prev_output = curr_output
                prev_cached = curr_cached
                prev_reasoning = curr_reasoning

            if not interaction_files:
                return None

            return SessionData(
                session_id=session_id,
                session_path=session_path,
                files=interaction_files,
                session_title=None,
            )

        except Exception:
            return None

    @staticmethod
    def load_all_sessions(
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        """Load all sessions from Codex.

        Args:
            base_path: Override base path
            limit: Maximum number of sessions to load

        Returns:
            List of SessionData objects sorted by start time (newest first)
        """
        session_files = CodexProcessor.find_session_files(base_path)

        if limit:
            session_files = session_files[:limit]

        sessions = []
        for session_file in session_files:
            session_data = CodexProcessor.load_session_data(session_file)
            if session_data:
                sessions.append(session_data)

        # Sort by start time (newest first)
        sessions.sort(
            key=lambda s: s.start_time or datetime.min,
            reverse=True,
        )

        return sessions

    @staticmethod
    def has_data(base_path: Optional[str] = None) -> bool:
        """Check if Codex has any session data.

        Args:
            base_path: Override base path

        Returns:
            True if there are JSONL files, False otherwise
        """
        session_files = CodexProcessor.find_session_files(base_path)
        return len(session_files) > 0
