"""Configuration management for OpenCode Monitor."""

import json
import os
import toml
import yaml
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator
from decimal import Decimal

from .models.limits import LimitsConfig, ProviderLimit, ModelLimit


def opencode_storage_path(path: str | None = None) -> str:
    base = os.getenv("XDG_DATA_HOME") or "~/.local/share"
    parts = [base, "opencode", "storage"]
    if path:
        parts.append(path)
    return os.path.join(*parts)


def claude_code_storage_path() -> str:
    """Get default Claude Code storage path."""
    return os.path.join("~", ".claude", "projects")


class PathsConfig(BaseModel):
    """Configuration for file paths."""

    messages_dir: str = Field(default=opencode_storage_path("message"))
    opencode_storage_dir: str = Field(default=opencode_storage_path())
    claude_code_storage_dir: str = Field(default=claude_code_storage_path())
    export_dir: str = Field(default="./exports")

    @field_validator(
        "messages_dir", "opencode_storage_dir", "claude_code_storage_dir", "export_dir"
    )
    @classmethod
    def expand_path(cls, v):
        """Expand user paths and environment variables."""
        return os.path.expanduser(os.path.expandvars(v))


class UIConfig(BaseModel):
    """Configuration for UI appearance."""

    table_style: str = Field(default="rich", pattern="^(rich|simple|minimal)$")
    progress_bars: bool = Field(default=True)
    colors: bool = Field(default=True)
    live_refresh_interval: int = Field(default=10, ge=1, le=60)
    session_max_hours: float = Field(
        default=5.0,
        ge=1.0,
        le=24.0,
        description="Maximum session duration for progress bar (hours)",
    )


class ExportConfig(BaseModel):
    """Configuration for data export."""

    default_format: str = Field(default="csv", pattern="^(csv|json)$")
    include_metadata: bool = Field(default=True)
    include_raw_data: bool = Field(default=False)


class ModelsConfig(BaseModel):
    """Configuration for model pricing."""

    config_file: str = Field(default="models.json")


class AnalyticsConfig(BaseModel):
    """Configuration for analytics."""

    default_timeframe: str = Field(default="daily", pattern="^(daily|weekly|monthly)$")
    recent_sessions_limit: int = Field(default=50, ge=1, le=1000)
    fallback_provider_ids: list[str] = Field(
        default=["fallback"],
        description="Provider IDs that act as fallback proxies. "
        "When detected, real provider/model is extracted from part metadata.",
    )
    default_source: str = Field(
        default="auto",
        pattern="^(opencode|claude-code|codex|crush|all|auto)$",
        description="Default data source: opencode, claude-code, codex, crush, all, or auto-detect",
    )


class CacheConfig(BaseModel):
    """Configuration for DuckDB cache."""

    enabled: bool = Field(
        default=True,
        description="Enable persistent DuckDB cache for fast session loading",
    )
    db_path: str = Field(
        default="~/.cache/omo-monitor/cache.duckdb",
        description="Path to DuckDB cache database file",
    )
    fresh_threshold_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        description="Consider data fresh if within this many minutes",
    )
    batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Number of records to commit per batch",
    )
    background_sync: bool = Field(
        default=True,
        description="Enable background syncing of historical data",
    )

    @field_validator("db_path")
    @classmethod
    def expand_db_path(cls, v):
        """Expand user paths and environment variables."""
        return os.path.expanduser(os.path.expandvars(v))


class PricingConfig(BaseModel):
    """Configuration for model pricing."""

    source: str = Field(
        default="local",
        pattern="^(local|models\\.dev|both)$",
        description="Pricing source: local (models.json), models.dev (API), or both",
    )
    fallback_to_local: bool = Field(
        default=True,
        description="Fall back to local pricing if Models.dev fails",
    )
    cache_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours to cache Models.dev pricing data",
    )
    api_url: str = Field(
        default="https://models.dev/api.json",
        description="Models.dev API URL",
    )


class Config(BaseModel):
    """Main configuration class."""

    paths: PathsConfig = Field(default_factory=PathsConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)


class ModelPricing(BaseModel):
    """Model for pricing information."""

    input: Decimal = Field(description="Cost per 1M input tokens")
    output: Decimal = Field(description="Cost per 1M output tokens")
    cache_write: Decimal = Field(
        alias="cacheWrite", description="Cost per 1M cache write tokens"
    )
    cache_read: Decimal = Field(
        alias="cacheRead", description="Cost per 1M cache read tokens"
    )
    context_window: int = Field(
        alias="contextWindow", description="Maximum context window size"
    )
    session_quota: Decimal = Field(
        alias="sessionQuota", description="Maximum session cost quota"
    )


class ConfigManager:
    """Manages configuration loading and access."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration manager.

        Args:
            config_path: Path to configuration file. If None, searches standard locations.
        """
        self.config_path = config_path or self._find_config_file()
        self._config: Optional[Config] = None
        self._pricing_data: Optional[Dict[str, ModelPricing]] = None
        self._limits_config: Optional[LimitsConfig] = None

    def _find_config_file(self) -> str:
        """Find configuration file in standard locations."""
        search_paths = [
            os.path.join(os.path.dirname(__file__), "config.toml"),
            os.path.expanduser("~/.config/omo-monitor/config.toml"),
            "config.toml",
            "omo_monitor.toml",
        ]

        for path in search_paths:
            if os.path.exists(path):
                return path

        # Return default path even if it doesn't exist
        return search_paths[0]

    @property
    def config(self) -> Config:
        """Get configuration, loading if necessary."""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> Config:
        """Load configuration from TOML file."""
        if not os.path.exists(self.config_path):
            # Return default configuration if file doesn't exist
            return Config()

        try:
            with open(self.config_path, "r") as f:
                config_data = toml.load(f)
            return Config(**config_data)
        except (toml.TomlDecodeError, ValueError) as e:
            raise ValueError(f"Invalid configuration file {self.config_path}: {e}")

    def load_pricing_data(self) -> Dict[str, ModelPricing]:
        """Load model pricing data."""
        if self._pricing_data is None:
            self._pricing_data = self._load_pricing_data()
        return self._pricing_data

    def _load_pricing_data(self) -> Dict[str, ModelPricing]:
        """Load pricing data from JSON file."""
        models_file = self.config.models.config_file

        # Try relative to config file first
        if not os.path.isabs(models_file):
            config_dir = os.path.dirname(self.config_path)
            models_file = os.path.join(config_dir, models_file)

        if not os.path.exists(models_file):
            # Try in same directory as this module
            models_file = os.path.join(os.path.dirname(__file__), "models.json")

        if not os.path.exists(models_file):
            return {}

        try:
            with open(models_file, "r") as f:
                raw_data = json.load(f)

            pricing_data = {}
            for model_name, model_data in raw_data.items():
                pricing_data[model_name] = ModelPricing(**model_data)

            return pricing_data
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid pricing file {models_file}: {e}")

    def get_model_pricing(self, model_name: str) -> Optional[ModelPricing]:
        """Get pricing information for a specific model."""
        pricing_data = self.load_pricing_data()
        return pricing_data.get(model_name)

    def reload(self):
        """Reload configuration and pricing data."""
        self._config = None
        self._pricing_data = None
        self._limits_config = None

    def _find_limits_file(self) -> Optional[str]:
        """Find limits configuration file."""
        search_paths = [
            os.path.expanduser("~/.config/omo-monitor/limits.yaml"),
            os.path.join(os.path.dirname(self.config_path), "limits.yaml"),
            os.path.join(os.path.dirname(__file__), "limits.yaml"),
            "limits.yaml",
        ]

        for path in search_paths:
            if os.path.exists(path):
                return path
        return None

    def load_limits_config(self) -> Optional[LimitsConfig]:
        """Load subscription limits configuration."""
        if self._limits_config is None:
            self._limits_config = self._load_limits_config()
        return self._limits_config

    def _load_limits_config(self) -> Optional[LimitsConfig]:
        """Load limits from YAML file."""
        limits_file = self._find_limits_file()
        if not limits_file:
            return None

        try:
            with open(limits_file, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            if not raw_data:
                return None

            # Parse providers
            providers = []
            for provider_data in raw_data.get("providers", []):
                # Parse model limits if present
                model_limits = []
                for ml_data in provider_data.pop("model_limits", []):
                    model_limits.append(ModelLimit(**ml_data))

                provider_data["model_limits"] = model_limits
                providers.append(ProviderLimit(**provider_data))

            return LimitsConfig(
                providers=providers,
                default_window_hours=raw_data.get("default_window_hours", 5),
            )
        except (yaml.YAMLError, ValueError) as e:
            # Log warning but don't fail - limits are optional
            import sys

            print(
                f"Warning: Could not load limits config from {limits_file}: {e}",
                file=sys.stderr,
            )
            return None

    def get_provider_limit(self, provider_id: str) -> Optional[ProviderLimit]:
        """Get limits for a specific provider."""
        limits = self.load_limits_config()
        if limits:
            return limits.get_provider_limit(provider_id)
        return None


# Global configuration manager instance
config_manager = ConfigManager()
