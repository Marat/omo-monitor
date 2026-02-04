"""DuckDB-based cache module for OmO-monitor.

Provides persistent caching for session data with:
- Fast incremental updates using file mtime tracking
- Crash recovery with progress checkpoints
- Background loading for historical data
"""

from .schema import CacheSchema
from .manager import CacheManager
from .progress import LoadProgressTracker
from .loader import IncrementalLoader, BackgroundLoader
from .cached_source import CachedDataSource

__all__ = [
    "CacheSchema",
    "CacheManager",
    "LoadProgressTracker",
    "IncrementalLoader",
    "BackgroundLoader",
    "CachedDataSource",
]
