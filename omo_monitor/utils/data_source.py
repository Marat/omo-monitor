"""Data source abstraction for OmO-monitor.

Provides unified interface for loading session data from different sources:
- OpenCode (original source)
- Claude Code (JSONL logs)
- Codex CLI (JSONL logs)
- Crush CLI (SQLite databases)
- Merged (combines multiple sources)
"""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models.session import SessionData


class DataSource(ABC):
    """Abstract base class for data sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this data source."""
        pass

    @property
    @abstractmethod
    def default_path(self) -> Optional[str]:
        """Get default base path for this data source."""
        pass

    @abstractmethod
    def has_data(self, base_path: Optional[str] = None) -> bool:
        """Check if this data source has any data.

        Args:
            base_path: Optional override path

        Returns:
            True if data exists, False otherwise
        """
        pass

    @abstractmethod
    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        """Find all session paths/files.

        Args:
            base_path: Optional override path

        Returns:
            List of session paths (directories for OpenCode, files for Claude Code)
        """
        pass

    @abstractmethod
    def load_session(self, session_path: Path) -> Optional[SessionData]:
        """Load a single session.

        Args:
            session_path: Path to session (directory or file)

        Returns:
            SessionData or None if loading failed
        """
        pass

    @abstractmethod
    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        """Load all sessions from this data source.

        Args:
            base_path: Optional override path
            limit: Maximum number of sessions to load

        Returns:
            List of SessionData objects
        """
        pass


class OpenCodeDataSource(DataSource):
    """Data source for OpenCode session directories."""

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def default_path(self) -> Optional[str]:
        try:
            from ..config import config_manager
            return config_manager.config.paths.messages_dir
        except ImportError:
            return None

    def has_data(self, base_path: Optional[str] = None) -> bool:
        from .file_utils import FileProcessor

        if base_path:
            sessions = FileProcessor.find_session_directories(base_path)
        else:
            try:
                from ..config import config_manager

                path = config_manager.config.paths.messages_dir
                sessions = FileProcessor.find_session_directories(path)
            except ImportError:
                return False

        return len(sessions) > 0

    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        from .file_utils import FileProcessor

        if not base_path:
            try:
                from ..config import config_manager

                base_path = config_manager.config.paths.messages_dir
            except ImportError:
                return []

        return FileProcessor.find_session_directories(base_path)

    def load_session(self, session_path: Path) -> Optional[SessionData]:
        from .file_utils import FileProcessor

        return FileProcessor.load_session_data(session_path)

    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        from .file_utils import FileProcessor

        if not base_path:
            try:
                from ..config import config_manager

                base_path = config_manager.config.paths.messages_dir
            except ImportError:
                return []

        return FileProcessor.load_all_sessions(base_path, limit)


class ClaudeCodeDataSource(DataSource):
    """Data source for Claude Code JSONL session logs."""

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def default_path(self) -> Optional[str]:
        from .claude_code_processor import ClaudeCodeProcessor
        path = ClaudeCodeProcessor.get_claude_code_storage_path()
        return str(path) if path else None

    def has_data(self, base_path: Optional[str] = None) -> bool:
        from .claude_code_processor import ClaudeCodeProcessor

        return ClaudeCodeProcessor.has_data(base_path)

    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        from .claude_code_processor import ClaudeCodeProcessor

        return ClaudeCodeProcessor.find_session_files(base_path)

    def load_session(self, session_path: Path) -> Optional[SessionData]:
        from .claude_code_processor import ClaudeCodeProcessor

        return ClaudeCodeProcessor.load_session_data(session_path)

    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        from .claude_code_processor import ClaudeCodeProcessor

        return ClaudeCodeProcessor.load_all_sessions(base_path, limit)


class CodexDataSource(DataSource):
    """Data source for Codex CLI JSONL session logs."""

    @property
    def name(self) -> str:
        return "codex"

    @property
    def default_path(self) -> Optional[str]:
        from .codex_processor import CodexProcessor
        path = CodexProcessor.get_codex_storage_path()
        return str(path) if path else None

    def has_data(self, base_path: Optional[str] = None) -> bool:
        from .codex_processor import CodexProcessor

        return CodexProcessor.has_data(base_path)

    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        from .codex_processor import CodexProcessor

        return CodexProcessor.find_session_files(base_path)

    def load_session(self, session_path: Path) -> Optional[SessionData]:
        from .codex_processor import CodexProcessor

        return CodexProcessor.load_session_data(session_path)

    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        from .codex_processor import CodexProcessor

        return CodexProcessor.load_all_sessions(base_path, limit)


class CrushDataSource(DataSource):
    """Data source for Crush CLI SQLite session databases."""

    @property
    def name(self) -> str:
        return "crush"

    @property
    def default_path(self) -> Optional[str]:
        # Crush uses projects.json to find databases, no single base path
        return None

    def has_data(self, base_path: Optional[str] = None) -> bool:
        from .crush_processor import CrushProcessor

        return CrushProcessor.has_data(base_path)

    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        from .crush_processor import CrushProcessor

        return CrushProcessor.find_session_databases(base_path)

    def load_session(self, session_path: Path) -> Optional[SessionData]:
        from .crush_processor import CrushProcessor

        return CrushProcessor.load_session_data(session_path)

    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        from .crush_processor import CrushProcessor

        return CrushProcessor.load_all_sessions(base_path, limit)


class MergedDataSource(DataSource):
    """Data source that combines sessions from multiple sources."""

    def __init__(self, sources: List[DataSource]):
        """Initialize with list of data sources to merge.

        Args:
            sources: List of DataSource instances to combine
        """
        self.sources = sources

    @property
    def name(self) -> str:
        names = [s.name for s in self.sources]
        return f"merged({'+'.join(names)})"

    @property
    def default_path(self) -> Optional[str]:
        # Return the first source's default path
        for source in self.sources:
            path = source.default_path
            if path:
                return path
        return None

    def has_data(self, base_path: Optional[str] = None) -> bool:
        return any(source.has_data(base_path) for source in self.sources)

    def find_sessions(self, base_path: Optional[str] = None) -> List[Path]:
        all_sessions = []
        for source in self.sources:
            try:
                # Each source uses its own default_path when base_path is None
                # or when base_path doesn't match this source's structure
                source_path = base_path

                # If base_path is provided but doesn't match this source's default,
                # let each source use its own default path
                if base_path and source.default_path:
                    # Check if base_path is specific to another source
                    # by checking if it's NOT the source's default path
                    source_default = Path(source.default_path).resolve()
                    given_path = Path(base_path).resolve()

                    # If the given path is NOT a parent/child of source's default,
                    # the source should use its own default
                    try:
                        given_path.relative_to(source_default)
                    except ValueError:
                        try:
                            source_default.relative_to(given_path)
                        except ValueError:
                            # Paths are unrelated, use source's own default
                            source_path = None

                sessions = source.find_sessions(source_path)
                all_sessions.extend(sessions)
            except Exception:
                pass  # Source may not exist or have errors
        return all_sessions

    def load_session(self, session_path: Path) -> Optional[SessionData]:
        # Try each source until one succeeds
        for source in self.sources:
            try:
                session = source.load_session(session_path)
                if session:
                    return session
            except Exception:
                pass
        return None

    def load_all_sessions(
        self,
        base_path: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionData]:
        all_sessions = []

        for source in self.sources:
            try:
                # Each source uses its own default_path when base_path is None
                # or when base_path doesn't match this source's structure
                source_path = base_path

                # If base_path is provided but doesn't match this source's default,
                # let each source use its own default path
                if base_path and source.default_path:
                    source_default = Path(source.default_path).resolve()
                    given_path = Path(base_path).resolve()

                    # If the given path is NOT a parent/child of source's default,
                    # the source should use its own default
                    try:
                        given_path.relative_to(source_default)
                    except ValueError:
                        try:
                            source_default.relative_to(given_path)
                        except ValueError:
                            # Paths are unrelated, use source's own default
                            source_path = None

                # Don't apply limit per-source, we'll apply it after merging
                sessions = source.load_all_sessions(source_path, limit=None)
                all_sessions.extend(sessions)
            except Exception:
                pass  # Source may not exist or have errors

        # Sort by start time (newest first)
        all_sessions.sort(
            key=lambda s: s.start_time or datetime.min,
            reverse=True,
        )

        # Apply limit after merging and sorting
        if limit:
            all_sessions = all_sessions[:limit]

        return all_sessions


def get_data_source(source_type: str) -> DataSource:
    """Factory function to get appropriate data source.

    Args:
        source_type: One of "opencode", "claude-code", "codex", "crush", "all", or "auto"

    Returns:
        Appropriate DataSource instance

    Raises:
        ValueError: If source_type is invalid
    """
    if source_type == "opencode":
        return OpenCodeDataSource()

    elif source_type == "claude-code":
        return ClaudeCodeDataSource()

    elif source_type == "codex":
        return CodexDataSource()

    elif source_type == "crush":
        return CrushDataSource()

    elif source_type == "all":
        return MergedDataSource([
            OpenCodeDataSource(),
            ClaudeCodeDataSource(),
            CodexDataSource(),
            CrushDataSource(),
        ])

    elif source_type == "auto":
        # Auto-detect which sources have data
        sources = []

        opencode_source = OpenCodeDataSource()
        if opencode_source.has_data():
            sources.append(opencode_source)

        claude_code_source = ClaudeCodeDataSource()
        if claude_code_source.has_data():
            sources.append(claude_code_source)

        codex_source = CodexDataSource()
        if codex_source.has_data():
            sources.append(codex_source)

        crush_source = CrushDataSource()
        if crush_source.has_data():
            sources.append(crush_source)

        if sources:
            if len(sources) == 1:
                return sources[0]
            return MergedDataSource(sources)

        # Fallback to OpenCode if no data found
        return OpenCodeDataSource()

    else:
        raise ValueError(
            f"Invalid source type: {source_type}. "
            "Must be one of: opencode, claude-code, codex, crush, all, auto"
        )


def get_default_source() -> DataSource:
    """Get the default data source based on configuration.

    Returns:
        DataSource instance based on config.analytics.default_source
    """
    try:
        from ..config import config_manager

        source_type = config_manager.config.analytics.default_source
        return get_data_source(source_type)
    except ImportError:
        return get_data_source("auto")
