"""Cache manager for OmO-monitor.

Provides main interface for DuckDB cache operations.
"""

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import duckdb

from .schema import CacheSchema
from ..models.session import SessionData, InteractionFile, TokenUsage


def get_default_cache_path() -> Path:
    """Get default cache database path.

    Returns:
        Path to cache database file
    """
    # Use XDG_CACHE_HOME or fallback
    if os.name == "nt":
        cache_base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache_base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

    cache_dir = cache_base / "omo-monitor"
    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir / "cache.duckdb"


class CacheManager:
    """Manages DuckDB cache for session data."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        read_only: bool = False,
    ):
        """Initialize cache manager.

        Args:
            db_path: Path to DuckDB database file (default: ~/.cache/omo-monitor/cache.duckdb)
            read_only: Open database in read-only mode
        """
        if db_path:
            self.db_path = Path(db_path).expanduser()
        else:
            self.db_path = get_default_cache_path()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._read_only = read_only
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection.

        Returns:
            DuckDB connection
        """
        if self._conn is None:
            self._conn = duckdb.connect(
                str(self.db_path),
                read_only=self._read_only,
            )
            # Initialize schema if needed
            if not self._read_only:
                if CacheSchema.needs_migration(self._conn):
                    CacheSchema.migrate(self._conn)
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "CacheManager":
        """Context manager entry."""
        self._get_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    # === File tracking ===

    def get_file_mtime(
        self,
        source_type: str,
        file_path: str,
    ) -> Optional[float]:
        """Get cached mtime for a file.

        Args:
            source_type: Source type (opencode, claude-code, etc.)
            file_path: Path to source file

        Returns:
            Cached mtime or None if not cached
        """
        conn = self._get_connection()
        result = conn.execute(
            """
            SELECT file_mtime FROM source_files
            WHERE source_type = ? AND file_path = ?
            """,
            [source_type, file_path],
        ).fetchone()
        return result[0] if result else None

    def get_file_record_count(
        self,
        source_type: str,
        file_path: str,
    ) -> int:
        """Get cached record count for a file.

        Args:
            source_type: Source type
            file_path: Path to source file

        Returns:
            Cached record count or 0 if not cached
        """
        conn = self._get_connection()
        result = conn.execute(
            """
            SELECT record_count FROM source_files
            WHERE source_type = ? AND file_path = ?
            """,
            [source_type, file_path],
        ).fetchone()
        return result[0] if result else 0

    def update_file_tracking(
        self,
        source_type: str,
        file_path: str,
        file_mtime: float,
        session_id: Optional[str] = None,
        record_count: int = 0,
        status: str = "synced",
    ) -> None:
        """Update file tracking information.

        Args:
            source_type: Source type
            file_path: Path to source file
            file_mtime: File modification time
            session_id: Associated session ID
            record_count: Number of records in file
            status: Sync status (synced, pending, error)
        """
        conn = self._get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO source_files
            (source_type, file_path, file_mtime, session_id, record_count, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [source_type, file_path, file_mtime, session_id, record_count, status],
        )

    def get_changed_files(
        self,
        source_type: str,
        file_mtimes: Dict[str, float],
    ) -> List[str]:
        """Find files that have changed since last sync.

        Args:
            source_type: Source type
            file_mtimes: Dict of file_path -> current mtime

        Returns:
            List of file paths that need reloading
        """
        if not file_mtimes:
            return []

        conn = self._get_connection()
        changed = []

        for file_path, current_mtime in file_mtimes.items():
            cached_mtime = self.get_file_mtime(source_type, file_path)
            if cached_mtime is None or current_mtime > cached_mtime:
                changed.append(file_path)

        return changed

    # === Session operations ===

    def store_session(
        self,
        session: SessionData,
        source_type: str,
    ) -> None:
        """Store session data in cache.

        Args:
            session: Session data to store
            source_type: Source type
        """
        conn = self._get_connection()

        # Store session summary
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (session_id, source_type, session_path, project_name,
             start_time, end_time, total_input, total_output,
             total_cache_read, total_cache_write, interaction_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                session.session_id,
                source_type,
                str(session.session_path),
                session.project_name,
                session.start_time,
                session.end_time,
                session.total_tokens.input,
                session.total_tokens.output,
                session.total_tokens.cache_read,
                session.total_tokens.cache_write,
                session.interaction_count,
            ],
        )

        # Store interactions
        for file in session.files:
            self.store_interaction(file, session.session_id, source_type)

    def store_interaction(
        self,
        interaction: InteractionFile,
        session_id: str,
        source_type: str,
    ) -> None:
        """Store single interaction in cache.

        Args:
            interaction: Interaction file data
            session_id: Parent session ID
            source_type: Source type
        """
        conn = self._get_connection()

        # Generate unique ID if not present
        interaction_id = interaction.message_id or f"{session_id}_{interaction.file_path.name}"

        created_at = None
        if interaction.time_data and interaction.time_data.created_datetime:
            created_at = interaction.time_data.created_datetime

        file_mtime = interaction.file_path.stat().st_mtime

        conn.execute(
            """
            INSERT OR REPLACE INTO interactions
            (id, session_id, source_type, file_path, model_id, provider_id,
             agent, category, project_path, input_tokens, output_tokens,
             cache_read, cache_write, reasoning_tokens, cost, created_at, file_mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                interaction_id,
                session_id,
                source_type,
                str(interaction.file_path),
                interaction.model_id,
                interaction.provider_id,
                interaction.agent,
                interaction.category,
                interaction.project_path,
                interaction.tokens.input,
                interaction.tokens.output,
                interaction.tokens.cache_read,
                interaction.tokens.cache_write,
                interaction.tokens.reasoning,
                float(interaction.cost) if interaction.cost else None,
                created_at,
                file_mtime,
            ],
        )

    def get_sessions_in_range(
        self,
        start_time: datetime,
        end_time: datetime,
        source_type: Optional[str] = None,
        project_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get session summaries in time range.

        Args:
            start_time: Start of time range
            end_time: End of time range
            source_type: Filter by source type (optional)
            project_filter: Filter by project name (partial match)

        Returns:
            List of session summary dicts
        """
        conn = self._get_connection()

        query = """
            SELECT session_id, source_type, session_path, project_name,
                   start_time, end_time, total_input, total_output,
                   total_cache_read, total_cache_write, interaction_count
            FROM sessions
            WHERE start_time >= ? AND start_time <= ?
        """
        params: List[Any] = [start_time, end_time]

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)

        if project_filter:
            query += " AND project_name LIKE ?"
            params.append(f"%{project_filter}%")

        query += " ORDER BY start_time DESC"

        result = conn.execute(query, params).fetchall()

        return [
            {
                "session_id": row[0],
                "source_type": row[1],
                "session_path": row[2],
                "project_name": row[3],
                "start_time": row[4],
                "end_time": row[5],
                "total_input": row[6],
                "total_output": row[7],
                "total_cache_read": row[8],
                "total_cache_write": row[9],
                "interaction_count": row[10],
            }
            for row in result
        ]

    def get_interactions_in_range(
        self,
        start_time: datetime,
        end_time: datetime,
        source_type: Optional[str] = None,
        project_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get interactions in time range.

        Args:
            start_time: Start of time range
            end_time: End of time range
            source_type: Filter by source type (optional)
            project_filter: Filter by project path (partial match)

        Returns:
            List of interaction dicts
        """
        conn = self._get_connection()

        query = """
            SELECT id, session_id, source_type, file_path, model_id, provider_id,
                   agent, category, project_path, input_tokens, output_tokens,
                   cache_read, cache_write, reasoning_tokens, cost, created_at
            FROM interactions
            WHERE created_at >= ? AND created_at <= ?
        """
        params: List[Any] = [start_time, end_time]

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)

        if project_filter:
            query += " AND project_path LIKE ?"
            params.append(f"%{project_filter}%")

        query += " ORDER BY created_at DESC"

        result = conn.execute(query, params).fetchall()

        return [
            {
                "id": row[0],
                "session_id": row[1],
                "source_type": row[2],
                "file_path": row[3],
                "model_id": row[4],
                "provider_id": row[5],
                "agent": row[6],
                "category": row[7],
                "project_path": row[8],
                "input_tokens": row[9],
                "output_tokens": row[10],
                "cache_read": row[11],
                "cache_write": row[12],
                "reasoning_tokens": row[13],
                "cost": row[14],
                "created_at": row[15],
            }
            for row in result
        ]

    # === Aggregation queries ===

    def get_provider_usage(
        self,
        start_time: datetime,
        end_time: datetime,
        project_filter: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get aggregated usage by provider.

        Args:
            start_time: Start of time range
            end_time: End of time range
            project_filter: Filter by project path (partial match)

        Returns:
            Dict of provider_id -> {requests, tokens, cost}
        """
        conn = self._get_connection()

        query = """
            SELECT provider_id,
                   COUNT(*) as requests,
                   SUM(input_tokens + output_tokens + cache_read + cache_write) as tokens,
                   SUM(COALESCE(cost, 0)) as cost
            FROM interactions
            WHERE created_at >= ? AND created_at <= ?
        """
        params: List[Any] = [start_time, end_time]

        if project_filter:
            query += " AND project_path LIKE ?"
            params.append(f"%{project_filter}%")

        query += " GROUP BY provider_id ORDER BY cost DESC"

        result = conn.execute(query, params).fetchall()

        return {
            row[0] or "unknown": {
                "requests": row[1],
                "tokens": row[2] or 0,
                "cost": Decimal(str(row[3])) if row[3] else Decimal("0"),
            }
            for row in result
        }

    def get_model_usage(
        self,
        start_time: datetime,
        end_time: datetime,
        project_filter: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get aggregated usage by model.

        Args:
            start_time: Start of time range
            end_time: End of time range
            project_filter: Filter by project path (partial match)

        Returns:
            Dict of model_id -> {requests, input_tokens, output_tokens, cache_read, cost}
        """
        conn = self._get_connection()

        query = """
            SELECT model_id,
                   COUNT(*) as requests,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read) as cache_read,
                   SUM(cache_write) as cache_write,
                   SUM(COALESCE(cost, 0)) as cost
            FROM interactions
            WHERE created_at >= ? AND created_at <= ?
        """
        params: List[Any] = [start_time, end_time]

        if project_filter:
            query += " AND project_path LIKE ?"
            params.append(f"%{project_filter}%")

        query += " GROUP BY model_id ORDER BY requests DESC"

        result = conn.execute(query, params).fetchall()

        return {
            row[0]: {
                "requests": row[1],
                "input_tokens": row[2] or 0,
                "output_tokens": row[3] or 0,
                "cache_read": row[4] or 0,
                "cache_write": row[5] or 0,
                "cost": Decimal(str(row[6])) if row[6] else Decimal("0"),
            }
            for row in result
        }

    def get_project_usage(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Dict[str, Any]]:
        """Get aggregated usage by project.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            Dict of project_name -> {sessions, interactions, tokens, cost}
        """
        conn = self._get_connection()

        result = conn.execute(
            """
            SELECT s.project_name,
                   COUNT(DISTINCT s.session_id) as sessions,
                   SUM(s.interaction_count) as interactions,
                   SUM(s.total_input + s.total_output + s.total_cache_read + s.total_cache_write) as tokens,
                   SUM(i.cost) as cost
            FROM sessions s
            LEFT JOIN (
                SELECT session_id, SUM(COALESCE(cost, 0)) as cost
                FROM interactions
                WHERE created_at >= ? AND created_at <= ?
                GROUP BY session_id
            ) i ON s.session_id = i.session_id
            WHERE s.start_time >= ? AND s.start_time <= ?
            GROUP BY s.project_name
            ORDER BY tokens DESC
            """,
            [start_time, end_time, start_time, end_time],
        ).fetchall()

        return {
            row[0] or "Unknown": {
                "sessions": row[1],
                "interactions": row[2] or 0,
                "tokens": row[3] or 0,
                "cost": Decimal(str(row[4])) if row[4] else Decimal("0"),
            }
            for row in result
        }

    # === Time coverage ===

    def get_time_coverage(
        self,
        source_type: str,
    ) -> List[Tuple[datetime, datetime]]:
        """Get cached time ranges for a source.

        Args:
            source_type: Source type

        Returns:
            List of (start, end) tuples representing cached ranges
        """
        conn = self._get_connection()

        result = conn.execute(
            """
            SELECT range_start, range_end FROM time_coverage
            WHERE source_type = ? AND is_complete = TRUE
            ORDER BY range_start
            """,
            [source_type],
        ).fetchall()

        return [(row[0], row[1]) for row in result]

    def add_time_coverage(
        self,
        source_type: str,
        start_time: datetime,
        end_time: datetime,
        is_complete: bool = True,
    ) -> None:
        """Add time coverage record.

        Args:
            source_type: Source type
            start_time: Start of covered range
            end_time: End of covered range
            is_complete: Whether the range is fully loaded
        """
        conn = self._get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO time_coverage
            (source_type, range_start, range_end, is_complete)
            VALUES (?, ?, ?, ?)
            """,
            [source_type, start_time, end_time, is_complete],
        )

    def find_gaps(
        self,
        source_type: str,
        requested_start: datetime,
        requested_end: datetime,
    ) -> List[Tuple[datetime, datetime]]:
        """Find gaps in time coverage.

        Args:
            source_type: Source type
            requested_start: Start of requested range
            requested_end: End of requested range

        Returns:
            List of (start, end) tuples representing uncovered ranges
        """
        covered = self.get_time_coverage(source_type)

        if not covered:
            return [(requested_start, requested_end)]

        gaps = []
        cursor = requested_start

        for start, end in covered:
            if start > cursor and cursor < requested_end:
                gap_end = min(start, requested_end)
                if gap_end > cursor:
                    gaps.append((cursor, gap_end))
            cursor = max(cursor, end)

        if cursor < requested_end:
            gaps.append((cursor, requested_end))

        return gaps

    # === Cache management ===

    def clear(self) -> None:
        """Clear all cached data."""
        conn = self._get_connection()
        CacheSchema.drop_all_tables(conn)
        CacheSchema.create_schema(conn)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        conn = self._get_connection()

        sessions_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        interactions_count = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        files_count = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]

        # Get source breakdown
        source_stats = conn.execute(
            """
            SELECT source_type, COUNT(*) as count
            FROM sessions GROUP BY source_type
            """
        ).fetchall()

        # Get time range
        time_range = conn.execute(
            """
            SELECT MIN(start_time), MAX(end_time) FROM sessions
            """
        ).fetchone()

        # Get database file size
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "sessions": sessions_count,
            "interactions": interactions_count,
            "source_files": files_count,
            "sources": {row[0]: row[1] for row in source_stats},
            "time_range": {
                "start": time_range[0],
                "end": time_range[1],
            } if time_range[0] else None,
            "db_size_bytes": db_size,
            "db_path": str(self.db_path),
        }

    def vacuum(self) -> None:
        """Optimize database storage."""
        conn = self._get_connection()
        conn.execute("VACUUM")
