"""Crush CLI log processor for OmO-monitor.

Handles parsing and processing of Crush SQLite session databases.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..models.session import (
    SessionData,
    InteractionFile,
    TokenUsage,
    TimeData,
)


def get_crush_projects_file() -> Optional[Path]:
    """Get path to Crush projects.json file.

    Returns:
        Path to projects.json or None if not found
    """
    # Windows: %LOCALAPPDATA%/crush/projects.json
    # Linux/Mac: ~/.local/share/crush/projects.json
    import platform

    if platform.system() == "Windows":
        local_app_data = os.environ.get(
            "LOCALAPPDATA", os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local")
        )
        projects_file = Path(local_app_data) / "crush" / "projects.json"
    else:
        home = Path.home()
        projects_file = home / ".local" / "share" / "crush" / "projects.json"

    if projects_file.exists():
        return projects_file

    return None


class CrushProcessor:
    """Handles Crush SQLite session databases."""

    @staticmethod
    def get_crush_projects() -> List[Dict[str, str]]:
        """Get list of Crush projects from projects.json.

        Returns:
            List of project dicts with 'path' and 'data_dir' keys
        """
        projects_file = get_crush_projects_file()
        if not projects_file:
            return []

        try:
            with open(projects_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("projects", [])
        except (json.JSONDecodeError, FileNotFoundError, PermissionError):
            return []

    @staticmethod
    def find_session_databases(base_path: Optional[str] = None) -> List[Path]:
        """Find all crush.db files in project directories.

        Args:
            base_path: Override - if provided, search for .crush directories here

        Returns:
            List of paths to crush.db files
        """
        db_files = []

        if base_path:
            # Search for .crush directories under base_path
            base = Path(base_path)
            if base.exists():
                for crush_dir in base.rglob(".crush"):
                    db_file = crush_dir / "crush.db"
                    if db_file.exists():
                        db_files.append(db_file)
        else:
            # Use projects.json to find databases
            projects = CrushProcessor.get_crush_projects()
            for project in projects:
                data_dir = project.get("data_dir", "")
                if data_dir:
                    db_file = Path(data_dir) / "crush.db"
                    if db_file.exists():
                        db_files.append(db_file)

        # Sort by modification time (most recent first)
        db_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return db_files

    @staticmethod
    def load_sessions_from_db(db_path: Path) -> List[SessionData]:
        """Load all sessions from a Crush database.

        Args:
            db_path: Path to crush.db file

        Returns:
            List of SessionData objects
        """
        sessions = []

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get all root sessions (parent_session_id IS NULL)
            cursor.execute("""
                SELECT
                    id, title, prompt_tokens, completion_tokens,
                    cost, created_at, updated_at
                FROM sessions
                WHERE parent_session_id IS NULL
                ORDER BY created_at DESC
            """)

            db_sessions = cursor.fetchall()

            for db_session in db_sessions:
                session_id = db_session["id"]

                # Get messages for this session
                cursor.execute("""
                    SELECT
                        id, role, model, provider,
                        created_at, finished_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC
                """, (session_id,))

                messages = cursor.fetchall()

                # Create InteractionFile objects from assistant messages
                interaction_files = []
                for msg in messages:
                    if msg["role"] != "assistant":
                        continue

                    # Calculate tokens per message (approximate - divide session total by messages)
                    assistant_count = sum(1 for m in messages if m["role"] == "assistant")
                    if assistant_count > 0:
                        tokens_input = db_session["prompt_tokens"] // assistant_count
                        tokens_output = db_session["completion_tokens"] // assistant_count
                    else:
                        tokens_input = 0
                        tokens_output = 0

                    tokens = TokenUsage(
                        input=tokens_input,
                        output=tokens_output,
                        cache_write=0,
                        cache_read=0,
                        reasoning=0,
                    )

                    time_data = None
                    if msg["created_at"]:
                        time_data = TimeData(created=msg["created_at"] * 1000)
                        if msg["finished_at"]:
                            time_data.completed = msg["finished_at"] * 1000

                    # Get project path from db_path
                    project_path = str(db_path.parent.parent)

                    interaction = InteractionFile(
                        file_path=db_path,
                        session_id=session_id,
                        message_id=msg["id"],
                        role="assistant",
                        parent_id=None,
                        model_id=msg["model"] or "unknown",
                        model_id_raw=msg["model"],
                        provider_id=msg["provider"] or "unknown",
                        tokens=tokens,
                        time_data=time_data,
                        cost=None,
                        agent=None,
                        mode=None,
                        category=None,
                        skills=[],
                        project_path=project_path,
                        root_path=None,
                        finish_reason=None,
                        summary=None,
                        system_prompt=None,
                        tools_config=None,
                        raw_data={},
                    )
                    interaction_files.append(interaction)

                if interaction_files:
                    session_data = SessionData(
                        session_id=session_id,
                        session_path=db_path,
                        files=interaction_files,
                        session_title=db_session["title"],
                    )
                    sessions.append(session_data)

            conn.close()

        except (sqlite3.Error, Exception):
            pass

        return sessions

    @staticmethod
    def load_session_data(session_path: Path) -> Optional[SessionData]:
        """Load a single session from database.

        For Crush, session_path should be a crush.db file.

        Args:
            session_path: Path to crush.db file

        Returns:
            First SessionData from the database or None
        """
        if not session_path.exists():
            return None

        if session_path.name != "crush.db":
            return None

        sessions = CrushProcessor.load_sessions_from_db(session_path)
        return sessions[0] if sessions else None

    @staticmethod
    def load_all_sessions(
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        """Load all sessions from all Crush project databases.

        Args:
            base_path: Override search path
            limit: Maximum number of sessions to load

        Returns:
            List of SessionData objects sorted by start time (newest first)
        """
        db_files = CrushProcessor.find_session_databases(base_path)

        all_sessions = []
        for db_file in db_files:
            sessions = CrushProcessor.load_sessions_from_db(db_file)
            all_sessions.extend(sessions)

        # Sort by start time (newest first)
        all_sessions.sort(
            key=lambda s: s.start_time or datetime.min,
            reverse=True,
        )

        if limit:
            all_sessions = all_sessions[:limit]

        return all_sessions

    @staticmethod
    def has_data(base_path: Optional[str] = None) -> bool:
        """Check if Crush has any session data.

        Args:
            base_path: Override search path

        Returns:
            True if there are databases with sessions, False otherwise
        """
        db_files = CrushProcessor.find_session_databases(base_path)
        return len(db_files) > 0
