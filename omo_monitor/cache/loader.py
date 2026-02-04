"""Incremental and background loading for cache.

Handles smart loading strategies:
- Incremental: Only reload changed files based on mtime
- Background: Load historical data in background thread
- Gap filling: Load missing time ranges
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Callable, Any, TYPE_CHECKING

from .manager import CacheManager
from .progress import LoadProgressTracker

if TYPE_CHECKING:
    from ..utils.data_source import DataSource
    from ..models.session import SessionData


class IncrementalLoader:
    """Handles incremental loading based on file mtime."""

    def __init__(
        self,
        cache: CacheManager,
        batch_size: int = 100,
    ):
        """Initialize incremental loader.

        Args:
            cache: Cache manager instance
            batch_size: Number of records to commit per batch
        """
        self.cache = cache
        self.batch_size = batch_size

    def load_source(
        self,
        data_source: "DataSource",
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> int:
        """Load data from source incrementally.

        Only reloads files that have changed since last sync.

        Args:
            data_source: Data source to load from
            progress_callback: Optional callback(file_path, current, total)

        Returns:
            Number of sessions loaded/updated
        """
        source_type = data_source.name
        conn = self.cache._get_connection()
        progress = LoadProgressTracker(conn)

        # Find all session paths
        session_paths = data_source.find_sessions()
        total_files = len(session_paths)

        if not session_paths:
            return 0

        # Check for interrupted loads
        interrupted = progress.get_interrupted_loads(source_type)
        resume_from: Optional[str] = None

        if interrupted:
            latest = interrupted[0]
            resume_from = latest.get("last_processed_path")
            load_id = latest["load_id"]
            # Mark as running again
            conn.execute(
                "UPDATE load_progress SET status = 'running' WHERE load_id = ?",
                [load_id],
            )
        else:
            load_id = progress.start_load(source_type, total_files=total_files)

        # Build mtime map for changed file detection
        file_mtimes = {}
        for path in session_paths:
            try:
                file_mtimes[str(path)] = path.stat().st_mtime
            except OSError:
                continue

        # Find changed files
        changed_files = self.cache.get_changed_files(source_type, file_mtimes)

        # If resuming, filter to files after resume point
        if resume_from:
            try:
                resume_idx = [str(p) for p in session_paths].index(resume_from)
                session_paths = session_paths[resume_idx:]
                changed_files = [f for f in changed_files if f in [str(p) for p in session_paths]]
            except ValueError:
                pass  # Resume path not found, process all

        loaded_count = 0
        batch_count = 0

        for i, session_path in enumerate(session_paths):
            path_str = str(session_path)

            # Skip unchanged files
            if path_str not in changed_files:
                continue

            try:
                session = data_source.load_session(session_path)

                if session and session.files:
                    self.cache.store_session(session, source_type)

                    # Update file tracking
                    self.cache.update_file_tracking(
                        source_type=source_type,
                        file_path=path_str,
                        file_mtime=file_mtimes.get(path_str, 0),
                        session_id=session.session_id,
                        record_count=len(session.files),
                    )

                    loaded_count += 1
                    batch_count += 1

                # Commit batch
                if batch_count >= self.batch_size:
                    progress.update_progress(load_id, path_str, i + 1)
                    batch_count = 0

                if progress_callback:
                    progress_callback(path_str, i + 1, total_files)

            except Exception:
                # Skip files with errors, continue loading
                continue

        # Final commit and complete
        progress.complete_load(load_id)

        return loaded_count

    def load_file_incremental(
        self,
        data_source: "DataSource",
        file_path: Path,
    ) -> bool:
        """Load single file if changed.

        Args:
            data_source: Data source
            file_path: Path to file

        Returns:
            True if file was loaded, False if unchanged
        """
        source_type = data_source.name
        path_str = str(file_path)

        try:
            current_mtime = file_path.stat().st_mtime
        except OSError:
            return False

        cached_mtime = self.cache.get_file_mtime(source_type, path_str)

        if cached_mtime is not None and current_mtime <= cached_mtime:
            return False  # Unchanged

        session = data_source.load_session(file_path)

        if session and session.files:
            self.cache.store_session(session, source_type)
            self.cache.update_file_tracking(
                source_type=source_type,
                file_path=path_str,
                file_mtime=current_mtime,
                session_id=session.session_id,
                record_count=len(session.files),
            )
            return True

        return False


class BackgroundLoader:
    """Handles background loading for historical data."""

    def __init__(
        self,
        cache: CacheManager,
        max_workers: int = 2,
    ):
        """Initialize background loader.

        Args:
            cache: Cache manager instance
            max_workers: Maximum concurrent loading threads
        """
        self.cache = cache
        self.max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._stop_event = threading.Event()
        self._active_loads: List[str] = []

    def start(self) -> None:
        """Start background executor."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self._stop_event.clear()

    def stop(self) -> None:
        """Stop background executor and wait for completion."""
        self._stop_event.set()
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None

    def schedule_gap_fill(
        self,
        data_source: "DataSource",
        start_time: datetime,
        end_time: datetime,
        callback: Optional[Callable[[str, bool], None]] = None,
    ) -> str:
        """Schedule background loading for a time gap.

        Args:
            data_source: Data source to load from
            start_time: Start of time range
            end_time: End of time range
            callback: Optional callback(load_id, success) when complete

        Returns:
            Load ID for tracking
        """
        if self._executor is None:
            self.start()

        conn = self.cache._get_connection()
        progress = LoadProgressTracker(conn)
        load_id = progress.start_load(
            data_source.name,
            time_range_start=start_time,
            time_range_end=end_time,
        )
        self._active_loads.append(load_id)

        self._executor.submit(
            self._load_worker,
            data_source,
            start_time,
            end_time,
            load_id,
            callback,
        )

        return load_id

    def _load_worker(
        self,
        data_source: "DataSource",
        start_time: datetime,
        end_time: datetime,
        load_id: str,
        callback: Optional[Callable[[str, bool], None]],
    ) -> None:
        """Background worker for loading data.

        Args:
            data_source: Data source
            start_time: Start of time range
            end_time: End of time range
            load_id: Load operation ID
            callback: Completion callback
        """
        conn = self.cache._get_connection()
        progress = LoadProgressTracker(conn)
        source_type = data_source.name
        success = False

        try:
            session_paths = data_source.find_sessions()
            loaded_count = 0

            for session_path in session_paths:
                if self._stop_event.is_set():
                    progress.mark_interrupted(load_id)
                    break

                try:
                    session = data_source.load_session(session_path)

                    if not session or not session.start_time:
                        continue

                    # Check if session is in time range
                    if session.start_time < start_time or session.start_time > end_time:
                        continue

                    self.cache.store_session(session, source_type)

                    # Update file tracking
                    try:
                        file_mtime = session_path.stat().st_mtime
                    except OSError:
                        file_mtime = 0

                    self.cache.update_file_tracking(
                        source_type=source_type,
                        file_path=str(session_path),
                        file_mtime=file_mtime,
                        session_id=session.session_id,
                        record_count=len(session.files),
                    )

                    loaded_count += 1
                    progress.update_progress(load_id, str(session_path))

                except Exception:
                    continue

            if not self._stop_event.is_set():
                progress.complete_load(load_id)

                # Mark time range as covered
                self.cache.add_time_coverage(
                    source_type,
                    start_time,
                    end_time,
                    is_complete=True,
                )

                success = True

        except Exception as e:
            progress.mark_error(load_id, str(e))

        finally:
            if load_id in self._active_loads:
                self._active_loads.remove(load_id)

            if callback:
                callback(load_id, success)

    def get_active_loads(self) -> List[str]:
        """Get list of active load IDs.

        Returns:
            List of active load operation IDs
        """
        return list(self._active_loads)

    def is_loading(self) -> bool:
        """Check if any loads are active.

        Returns:
            True if background loading is in progress
        """
        return len(self._active_loads) > 0


class SmartLoader:
    """Coordinates incremental and background loading.

    Implements the smart load algorithm:
    1. IMMEDIATE (blocking): Load fresh data from cache_end to now
    2. BACKGROUND: Fill historical gaps in background
    """

    def __init__(
        self,
        cache: CacheManager,
        batch_size: int = 100,
        fresh_threshold_minutes: int = 30,
    ):
        """Initialize smart loader.

        Args:
            cache: Cache manager instance
            batch_size: Batch size for incremental loader
            fresh_threshold_minutes: Consider data fresh if within this time
        """
        self.cache = cache
        self.incremental = IncrementalLoader(cache, batch_size)
        self.background = BackgroundLoader(cache)
        self.fresh_threshold = timedelta(minutes=fresh_threshold_minutes)

    def load_with_strategy(
        self,
        data_source: "DataSource",
        requested_hours: float,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict:
        """Load data with smart strategy.

        Args:
            data_source: Data source to load from
            requested_hours: Hours of history to load
            progress_callback: Progress callback for incremental load

        Returns:
            Dict with load statistics
        """
        source_type = data_source.name
        now = datetime.now()
        requested_start = now - timedelta(hours=requested_hours)

        # Check what we have cached
        coverage = self.cache.get_time_coverage(source_type)

        # Determine cache_end (most recent cached data)
        cache_end = None
        for start, end in coverage:
            if cache_end is None or end > cache_end:
                cache_end = end

        result = {
            "immediate_loaded": 0,
            "background_scheduled": False,
            "gaps_found": [],
        }

        # IMMEDIATE: Load fresh data (blocking)
        fresh_start = cache_end if cache_end else requested_start
        if now - fresh_start > self.fresh_threshold:
            # Need to load fresh data
            result["immediate_loaded"] = self.incremental.load_source(
                data_source,
                progress_callback,
            )

            # Update coverage for fresh load
            self.cache.add_time_coverage(
                source_type,
                fresh_start,
                now,
                is_complete=True,
            )

        # BACKGROUND: Fill historical gaps
        gaps = self.cache.find_gaps(source_type, requested_start, now)
        result["gaps_found"] = gaps

        for gap_start, gap_end in gaps:
            # Skip recent gaps (handled by immediate load)
            if now - gap_end < self.fresh_threshold:
                continue

            self.background.schedule_gap_fill(
                data_source,
                gap_start,
                gap_end,
            )
            result["background_scheduled"] = True

        return result

    def stop_background(self) -> None:
        """Stop background loading."""
        self.background.stop()
