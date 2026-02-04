"""DuckDB schema definitions for OmO-monitor cache.

Provides schema creation and migration for the cache database.
"""

from typing import Optional
import duckdb


class CacheSchema:
    """Manages DuckDB schema for cache database."""

    SCHEMA_VERSION = 1

    # SQL statements for creating tables
    CREATE_CACHE_META = """
    CREATE TABLE IF NOT EXISTS cache_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """

    CREATE_SOURCE_FILES = """
    CREATE TABLE IF NOT EXISTS source_files (
        source_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_mtime DOUBLE NOT NULL,
        session_id TEXT,
        record_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'synced',
        PRIMARY KEY (source_type, file_path)
    )
    """

    CREATE_SESSIONS = """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        session_path TEXT NOT NULL,
        project_name TEXT,
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        total_input INTEGER DEFAULT 0,
        total_output INTEGER DEFAULT 0,
        total_cache_read INTEGER DEFAULT 0,
        total_cache_write INTEGER DEFAULT 0,
        interaction_count INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """

    CREATE_SESSIONS_INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(start_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_name)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source_type)",
    ]

    CREATE_INTERACTIONS = """
    CREATE TABLE IF NOT EXISTS interactions (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        model_id TEXT NOT NULL,
        provider_id TEXT,
        agent TEXT,
        category TEXT,
        project_path TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cache_read INTEGER DEFAULT 0,
        cache_write INTEGER DEFAULT 0,
        reasoning_tokens INTEGER DEFAULT 0,
        cost DOUBLE,
        created_at TIMESTAMP,
        file_mtime DOUBLE NOT NULL
    )
    """

    CREATE_INTERACTIONS_INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_inter_time ON interactions(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_inter_session ON interactions(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_inter_provider ON interactions(provider_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_inter_model ON interactions(model_id)",
        "CREATE INDEX IF NOT EXISTS idx_inter_project ON interactions(project_path)",
    ]

    CREATE_LOAD_PROGRESS = """
    CREATE TABLE IF NOT EXISTS load_progress (
        load_id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        time_range_start TIMESTAMP,
        time_range_end TIMESTAMP,
        total_files INTEGER DEFAULT 0,
        processed_files INTEGER DEFAULT 0,
        last_processed_path TEXT,
        status TEXT DEFAULT 'running',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """

    CREATE_TIME_COVERAGE = """
    CREATE TABLE IF NOT EXISTS time_coverage (
        source_type TEXT NOT NULL,
        range_start TIMESTAMP NOT NULL,
        range_end TIMESTAMP NOT NULL,
        is_complete BOOLEAN DEFAULT FALSE,
        PRIMARY KEY (source_type, range_start, range_end)
    )
    """

    @classmethod
    def create_schema(cls, conn: duckdb.DuckDBPyConnection) -> None:
        """Create all tables and indexes.

        Args:
            conn: DuckDB connection
        """
        # Create tables
        conn.execute(cls.CREATE_CACHE_META)
        conn.execute(cls.CREATE_SOURCE_FILES)
        conn.execute(cls.CREATE_SESSIONS)
        conn.execute(cls.CREATE_INTERACTIONS)
        conn.execute(cls.CREATE_LOAD_PROGRESS)
        conn.execute(cls.CREATE_TIME_COVERAGE)

        # Create indexes
        for idx_sql in cls.CREATE_SESSIONS_INDEXES:
            conn.execute(idx_sql)
        for idx_sql in cls.CREATE_INTERACTIONS_INDEXES:
            conn.execute(idx_sql)

        # Set schema version
        conn.execute(
            """
            INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
            VALUES ('schema_version', ?, CURRENT_TIMESTAMP)
            """,
            [str(cls.SCHEMA_VERSION)],
        )

    @classmethod
    def get_schema_version(cls, conn: duckdb.DuckDBPyConnection) -> Optional[int]:
        """Get current schema version from database.

        Args:
            conn: DuckDB connection

        Returns:
            Schema version or None if not set
        """
        try:
            result = conn.execute(
                "SELECT value FROM cache_meta WHERE key = 'schema_version'"
            ).fetchone()
            if result:
                return int(result[0])
        except duckdb.CatalogException:
            pass
        return None

    @classmethod
    def needs_migration(cls, conn: duckdb.DuckDBPyConnection) -> bool:
        """Check if schema needs migration.

        Args:
            conn: DuckDB connection

        Returns:
            True if migration is needed
        """
        current_version = cls.get_schema_version(conn)
        return current_version is None or current_version < cls.SCHEMA_VERSION

    @classmethod
    def migrate(cls, conn: duckdb.DuckDBPyConnection) -> None:
        """Migrate schema to latest version.

        Args:
            conn: DuckDB connection
        """
        current_version = cls.get_schema_version(conn)

        if current_version is None:
            # Fresh install
            cls.create_schema(conn)
            return

        # Add migration steps here for future versions
        # if current_version < 2:
        #     cls._migrate_v1_to_v2(conn)

        # Update version
        conn.execute(
            """
            INSERT OR REPLACE INTO cache_meta (key, value, updated_at)
            VALUES ('schema_version', ?, CURRENT_TIMESTAMP)
            """,
            [str(cls.SCHEMA_VERSION)],
        )

    @classmethod
    def drop_all_tables(cls, conn: duckdb.DuckDBPyConnection) -> None:
        """Drop all tables (for cache clear).

        Args:
            conn: DuckDB connection
        """
        tables = [
            "time_coverage",
            "load_progress",
            "interactions",
            "sessions",
            "source_files",
            "cache_meta",
        ]
        for table in tables:
            try:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            except duckdb.CatalogException:
                pass
