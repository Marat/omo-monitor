"""Load progress tracking for crash recovery.

Tracks loading progress to enable resume after interruption.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import duckdb


class LoadProgressTracker:
    """Tracks loading progress for crash recovery."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """Initialize progress tracker.

        Args:
            conn: DuckDB connection
        """
        self._conn = conn

    def start_load(
        self,
        source_type: str,
        time_range_start: Optional[datetime] = None,
        time_range_end: Optional[datetime] = None,
        total_files: int = 0,
    ) -> str:
        """Start a new load operation.

        Args:
            source_type: Source type being loaded
            time_range_start: Start of time range being loaded
            time_range_end: End of time range being loaded
            total_files: Total number of files to process

        Returns:
            Load ID for tracking
        """
        load_id = str(uuid.uuid4())[:8]

        self._conn.execute(
            """
            INSERT INTO load_progress
            (load_id, source_type, time_range_start, time_range_end,
             total_files, processed_files, status, started_at)
            VALUES (?, ?, ?, ?, ?, 0, 'running', CURRENT_TIMESTAMP)
            """,
            [load_id, source_type, time_range_start, time_range_end, total_files],
        )

        return load_id

    def update_progress(
        self,
        load_id: str,
        last_processed_path: str,
        processed_files: Optional[int] = None,
    ) -> None:
        """Update load progress.

        Args:
            load_id: Load operation ID
            last_processed_path: Path of last processed file
            processed_files: Current count of processed files
        """
        if processed_files is not None:
            self._conn.execute(
                """
                UPDATE load_progress
                SET last_processed_path = ?, processed_files = ?
                WHERE load_id = ?
                """,
                [last_processed_path, processed_files, load_id],
            )
        else:
            self._conn.execute(
                """
                UPDATE load_progress
                SET last_processed_path = ?, processed_files = processed_files + 1
                WHERE load_id = ?
                """,
                [last_processed_path, load_id],
            )

    def complete_load(self, load_id: str) -> None:
        """Mark load as completed.

        Args:
            load_id: Load operation ID
        """
        self._conn.execute(
            """
            UPDATE load_progress
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE load_id = ?
            """,
            [load_id],
        )

    def mark_error(self, load_id: str, error_message: str) -> None:
        """Mark load as failed with error.

        Args:
            load_id: Load operation ID
            error_message: Error description
        """
        self._conn.execute(
            """
            UPDATE load_progress
            SET status = 'error', completed_at = CURRENT_TIMESTAMP
            WHERE load_id = ?
            """,
            [load_id],
        )
        # Also log error in cache_meta for debugging
        self._conn.execute(
            """
            INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            [f"load_error_{load_id}", error_message],
        )

    def mark_interrupted(self, load_id: str) -> None:
        """Mark load as interrupted (for resume).

        Args:
            load_id: Load operation ID
        """
        self._conn.execute(
            """
            UPDATE load_progress
            SET status = 'interrupted'
            WHERE load_id = ?
            """,
            [load_id],
        )

    def get_interrupted_loads(
        self,
        source_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find interrupted loads that can be resumed.

        Args:
            source_type: Filter by source type (optional)

        Returns:
            List of interrupted load records
        """
        query = """
            SELECT load_id, source_type, time_range_start, time_range_end,
                   total_files, processed_files, last_processed_path, started_at
            FROM load_progress
            WHERE status IN ('running', 'interrupted')
        """
        params: List[Any] = []

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)

        query += " ORDER BY started_at DESC"

        result = self._conn.execute(query, params).fetchall()

        return [
            {
                "load_id": row[0],
                "source_type": row[1],
                "time_range_start": row[2],
                "time_range_end": row[3],
                "total_files": row[4],
                "processed_files": row[5],
                "last_processed_path": row[6],
                "started_at": row[7],
            }
            for row in result
        ]

    def get_load_status(self, load_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific load.

        Args:
            load_id: Load operation ID

        Returns:
            Load status dict or None if not found
        """
        result = self._conn.execute(
            """
            SELECT load_id, source_type, time_range_start, time_range_end,
                   total_files, processed_files, last_processed_path,
                   status, started_at, completed_at
            FROM load_progress
            WHERE load_id = ?
            """,
            [load_id],
        ).fetchone()

        if not result:
            return None

        return {
            "load_id": result[0],
            "source_type": result[1],
            "time_range_start": result[2],
            "time_range_end": result[3],
            "total_files": result[4],
            "processed_files": result[5],
            "last_processed_path": result[6],
            "status": result[7],
            "started_at": result[8],
            "completed_at": result[9],
        }

    def cleanup_old_loads(self, days: int = 7) -> int:
        """Clean up old completed/error load records.

        Args:
            days: Delete records older than this many days

        Returns:
            Number of records deleted
        """
        result = self._conn.execute(
            """
            DELETE FROM load_progress
            WHERE status IN ('completed', 'error')
              AND completed_at < CURRENT_TIMESTAMP - INTERVAL ? DAY
            """,
            [days],
        )
        return result.fetchone()[0] if result else 0

    def cleanup_stale_running(self, hours: int = 24) -> int:
        """Mark stale 'running' loads as interrupted.

        Loads that have been 'running' for too long are likely crashed.

        Args:
            hours: Mark as interrupted if running longer than this

        Returns:
            Number of records updated
        """
        self._conn.execute(
            """
            UPDATE load_progress
            SET status = 'interrupted'
            WHERE status = 'running'
              AND started_at < CURRENT_TIMESTAMP - INTERVAL ? HOUR
            """,
            [hours],
        )
        return 0  # DuckDB doesn't return affected rows easily

    def get_recent_loads(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent load operations.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of recent load records
        """
        result = self._conn.execute(
            """
            SELECT load_id, source_type, time_range_start, time_range_end,
                   total_files, processed_files, status, started_at, completed_at
            FROM load_progress
            ORDER BY started_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

        return [
            {
                "load_id": row[0],
                "source_type": row[1],
                "time_range_start": row[2],
                "time_range_end": row[3],
                "total_files": row[4],
                "processed_files": row[5],
                "status": row[6],
                "started_at": row[7],
                "completed_at": row[8],
            }
            for row in result
        ]
