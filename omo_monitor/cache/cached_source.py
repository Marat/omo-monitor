"""Cached data source wrapper.

Wraps existing DataSource with transparent DuckDB caching.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .manager import CacheManager
from .loader import SmartLoader
from ..models.session import SessionData, InteractionFile, TokenUsage, TimeData

if TYPE_CHECKING:
    from ..utils.data_source import DataSource


class CachedDataSource:
    """Wraps a DataSource with transparent caching.

    Provides the same interface as DataSource but uses DuckDB cache
    for fast queries and incremental updates.
    """

    def __init__(
        self,
        source: "DataSource",
        cache: Optional[CacheManager] = None,
        enabled: bool = True,
        fresh_threshold_minutes: int = 30,
        batch_size: int = 100,
    ):
        """Initialize cached data source.

        Args:
            source: Underlying data source
            cache: Cache manager (creates default if None)
            enabled: Whether caching is enabled
            fresh_threshold_minutes: Consider data fresh if within this time
            batch_size: Batch size for loading
        """
        self._source = source
        self._enabled = enabled
        self._fresh_threshold = fresh_threshold_minutes
        self._batch_size = batch_size

        if enabled:
            self._cache = cache or CacheManager()
            self._loader = SmartLoader(
                self._cache,
                batch_size=batch_size,
                fresh_threshold_minutes=fresh_threshold_minutes,
            )
        else:
            self._cache = None
            self._loader = None

    @property
    def name(self) -> str:
        """Get source name."""
        return self._source.name

    @property
    def default_path(self) -> Optional[str]:
        """Get default path."""
        return self._source.default_path

    @property
    def cache_enabled(self) -> bool:
        """Check if caching is enabled."""
        return self._enabled and self._cache is not None

    def enable_cache(self) -> None:
        """Enable caching."""
        if not self._cache:
            self._cache = CacheManager()
            self._loader = SmartLoader(
                self._cache,
                batch_size=self._batch_size,
                fresh_threshold_minutes=self._fresh_threshold,
            )
        self._enabled = True

    def disable_cache(self) -> None:
        """Disable caching."""
        self._enabled = False

    def has_data(self, base_path: Optional[str] = None) -> bool:
        """Check if data exists."""
        return self._source.has_data(base_path)

    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        """Find all session paths."""
        return self._source.find_sessions(base_path)

    def load_session(self, session_path: Path) -> Optional[SessionData]:
        """Load single session (bypasses cache for individual loads)."""
        return self._source.load_session(session_path)

    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        """Load all sessions, using cache if enabled."""
        if not self.cache_enabled:
            return self._source.load_all_sessions(base_path, limit)

        # Sync cache first
        self._loader.incremental.load_source(self._source)

        # Load from cache
        return self._source.load_all_sessions(base_path, limit)

    def load_sessions_in_range(
        self,
        hours: float,
        project_filter: Optional[str] = None,
        use_cache: bool = True,
    ) -> List[SessionData]:
        """Load sessions within time range.

        Args:
            hours: Hours of history to load
            project_filter: Filter by project name
            use_cache: Whether to use cache (if enabled)

        Returns:
            List of sessions in time range
        """
        if not self.cache_enabled or not use_cache:
            # Fallback to direct loading with time filter
            sessions = self._source.load_all_sessions()
            cutoff = datetime.now() - timedelta(hours=hours)

            filtered = []
            for session in sessions:
                if session.start_time and session.start_time >= cutoff:
                    if project_filter:
                        if project_filter.lower() in session.project_name.lower():
                            filtered.append(session)
                    else:
                        filtered.append(session)

            return filtered

        # Use smart loading with cache
        self._loader.load_with_strategy(self._source, hours)

        # Query from cache
        now = datetime.now()
        start_time = now - timedelta(hours=hours)

        cached_sessions = self._cache.get_sessions_in_range(
            start_time,
            now,
            source_type=self._source.name,
            project_filter=project_filter,
        )

        # Convert cached data back to SessionData objects
        return self._convert_cached_sessions(cached_sessions, start_time, now)

    def _convert_cached_sessions(
        self,
        cached_sessions: List[Dict[str, Any]],
        start_time: datetime,
        end_time: datetime,
    ) -> List[SessionData]:
        """Convert cached session dicts to SessionData objects.

        Args:
            cached_sessions: List of session dicts from cache
            start_time: Start of time range
            end_time: End of time range

        Returns:
            List of SessionData objects
        """
        sessions = []

        for cached in cached_sessions:
            # Get interactions for this session
            interactions = self._cache.get_interactions_in_range(
                start_time,
                end_time,
                source_type=cached["source_type"],
            )

            # Filter to this session's interactions
            session_interactions = [
                i for i in interactions
                if i["session_id"] == cached["session_id"]
            ]

            # Convert to InteractionFile objects
            files = []
            for inter in session_interactions:
                tokens = TokenUsage(
                    input=inter["input_tokens"],
                    output=inter["output_tokens"],
                    cache_read=inter["cache_read"],
                    cache_write=inter["cache_write"],
                    reasoning=inter["reasoning_tokens"],
                )

                time_data = None
                if inter["created_at"]:
                    created_ms = int(inter["created_at"].timestamp() * 1000)
                    time_data = TimeData(created=created_ms)

                file = InteractionFile(
                    file_path=Path(inter["file_path"]),
                    session_id=inter["session_id"],
                    message_id=inter["id"],
                    role="assistant",
                    model_id=inter["model_id"],
                    provider_id=inter["provider_id"],
                    tokens=tokens,
                    time_data=time_data,
                    cost=inter["cost"],
                    agent=inter["agent"],
                    category=inter["category"],
                    project_path=inter["project_path"],
                )
                files.append(file)

            # Create SessionData
            session = SessionData(
                session_id=cached["session_id"],
                session_path=Path(cached["session_path"]),
                files=files,
            )
            sessions.append(session)

        return sessions

    def get_provider_usage(
        self,
        hours: float,
        project_filter: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get aggregated provider usage from cache.

        Args:
            hours: Hours of history
            project_filter: Filter by project

        Returns:
            Dict of provider -> usage stats
        """
        if not self.cache_enabled:
            return {}

        # Ensure cache is synced
        self._loader.load_with_strategy(self._source, hours)

        now = datetime.now()
        start_time = now - timedelta(hours=hours)

        return self._cache.get_provider_usage(start_time, now, project_filter)

    def get_model_usage(
        self,
        hours: float,
        project_filter: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get aggregated model usage from cache.

        Args:
            hours: Hours of history
            project_filter: Filter by project

        Returns:
            Dict of model -> usage stats
        """
        if not self.cache_enabled:
            return {}

        # Ensure cache is synced
        self._loader.load_with_strategy(self._source, hours)

        now = datetime.now()
        start_time = now - timedelta(hours=hours)

        return self._cache.get_model_usage(start_time, now, project_filter)

    def get_project_usage(
        self,
        hours: float,
    ) -> Dict[str, Dict[str, Any]]:
        """Get aggregated project usage from cache.

        Args:
            hours: Hours of history

        Returns:
            Dict of project -> usage stats
        """
        if not self.cache_enabled:
            return {}

        # Ensure cache is synced
        self._loader.load_with_strategy(self._source, hours)

        now = datetime.now()
        start_time = now - timedelta(hours=hours)

        return self._cache.get_project_usage(start_time, now)

    def sync_cache(
        self,
        progress_callback=None,
    ) -> int:
        """Manually sync cache with source.

        Args:
            progress_callback: Progress callback

        Returns:
            Number of sessions synced
        """
        if not self.cache_enabled:
            return 0

        return self._loader.incremental.load_source(
            self._source,
            progress_callback,
        )

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Cache stats dict
        """
        if not self.cache_enabled:
            return {"enabled": False}

        stats = self._cache.get_stats()
        stats["enabled"] = True
        return stats

    def clear_cache(self) -> None:
        """Clear all cached data."""
        if self._cache:
            self._cache.clear()

    def close(self) -> None:
        """Close cache connection."""
        if self._loader:
            self._loader.stop_background()
        if self._cache:
            self._cache.close()


def wrap_with_cache(
    source: "DataSource",
    enabled: bool = True,
    **kwargs,
) -> CachedDataSource:
    """Convenience function to wrap a DataSource with caching.

    Args:
        source: Data source to wrap
        enabled: Whether to enable caching
        **kwargs: Additional args for CachedDataSource

    Returns:
        CachedDataSource wrapper
    """
    return CachedDataSource(source, enabled=enabled, **kwargs)
