"""Models.dev API client for model pricing.

Fetches and caches model pricing from https://models.dev/api.json
"""

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Any

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_pricing_cache_path() -> Path:
    """Get path for pricing cache file.

    Returns:
        Path to pricing cache JSON file
    """
    if os.name == "nt":
        cache_base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        cache_base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

    cache_dir = cache_base / "omo-monitor"
    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir / "models_pricing.json"


class ModelPricingData:
    """Represents pricing data for a model."""

    def __init__(
        self,
        input_price: Decimal,
        output_price: Decimal,
        cache_read_price: Decimal = Decimal("0"),
        cache_write_price: Decimal = Decimal("0"),
        context_window: int = 200000,
        session_quota: Decimal = Decimal("0"),
    ):
        """Initialize pricing data.

        Args:
            input_price: Cost per 1M input tokens
            output_price: Cost per 1M output tokens
            cache_read_price: Cost per 1M cache read tokens
            cache_write_price: Cost per 1M cache write tokens
            context_window: Maximum context window size
            session_quota: Maximum session cost quota
        """
        self.input = input_price
        self.output = output_price
        self.cache_read = cache_read_price
        self.cache_write = cache_write_price
        self.context_window = context_window
        self.session_quota = session_quota

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dict representation
        """
        return {
            "input": str(self.input),
            "output": str(self.output),
            "cacheRead": str(self.cache_read),
            "cacheWrite": str(self.cache_write),
            "contextWindow": self.context_window,
            "sessionQuota": str(self.session_quota),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelPricingData":
        """Create from dictionary.

        Args:
            data: Dictionary with pricing data

        Returns:
            ModelPricingData instance
        """
        return cls(
            input_price=Decimal(str(data.get("input", 0))),
            output_price=Decimal(str(data.get("output", 0))),
            cache_read_price=Decimal(str(data.get("cacheRead", data.get("cache_read", 0)))),
            cache_write_price=Decimal(str(data.get("cacheWrite", data.get("cache_write", 0)))),
            context_window=int(data.get("contextWindow", data.get("context_window", 200000))),
            session_quota=Decimal(str(data.get("sessionQuota", data.get("session_quota", 0)))),
        )


class ModelsDevClient:
    """Client for Models.dev pricing API."""

    API_URL = "https://models.dev/api.json"
    DEFAULT_CACHE_TTL_HOURS = 24

    def __init__(
        self,
        cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
        api_url: Optional[str] = None,
        cache_path: Optional[Path] = None,
    ):
        """Initialize Models.dev client.

        Args:
            cache_ttl_hours: Hours to cache pricing data
            api_url: Override API URL
            cache_path: Override cache file path
        """
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.api_url = api_url or self.API_URL
        self.cache_path = cache_path or get_pricing_cache_path()
        self._cached_data: Optional[Dict[str, ModelPricingData]] = None
        self._cache_time: Optional[datetime] = None

    def fetch_pricing(self, force_refresh: bool = False) -> Dict[str, ModelPricingData]:
        """Fetch pricing data, using cache if valid.

        Args:
            force_refresh: Force API fetch even if cache is valid

        Returns:
            Dict of model_id -> ModelPricingData
        """
        # Check memory cache
        if not force_refresh and self._is_memory_cache_valid():
            return self._cached_data

        # Check file cache
        if not force_refresh:
            file_data = self._load_file_cache()
            if file_data:
                self._cached_data = file_data
                self._cache_time = datetime.now()
                return file_data

        # Fetch from API
        api_data = self._fetch_from_api()
        if api_data:
            self._cached_data = api_data
            self._cache_time = datetime.now()
            self._save_file_cache(api_data)
            return api_data

        # Fallback to stale cache if API fails
        if self._cached_data:
            return self._cached_data

        # Try loading stale file cache
        stale_data = self._load_file_cache(ignore_ttl=True)
        if stale_data:
            return stale_data

        return {}

    def _is_memory_cache_valid(self) -> bool:
        """Check if memory cache is still valid.

        Returns:
            True if cache is valid
        """
        if not self._cached_data or not self._cache_time:
            return False
        return datetime.now() - self._cache_time < self.cache_ttl

    def _load_file_cache(self, ignore_ttl: bool = False) -> Optional[Dict[str, ModelPricingData]]:
        """Load pricing from file cache.

        Args:
            ignore_ttl: Load even if cache is expired

        Returns:
            Cached pricing data or None
        """
        if not self.cache_path.exists():
            return None

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # Check TTL
            if not ignore_ttl:
                cached_at = datetime.fromisoformat(cache_data.get("cached_at", ""))
                if datetime.now() - cached_at >= self.cache_ttl:
                    return None

            # Parse models
            models = cache_data.get("models", {})
            return self._parse_api_response(models)

        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def _save_file_cache(self, data: Dict[str, ModelPricingData]) -> None:
        """Save pricing to file cache.

        Args:
            data: Pricing data to cache
        """
        try:
            cache_data = {
                "cached_at": datetime.now().isoformat(),
                "source": self.api_url,
                "models": {
                    model_id: pricing.to_dict()
                    for model_id, pricing in data.items()
                },
            }

            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)

        except (OSError, json.JSONEncodeError):
            pass  # Cache write failure is non-fatal

    def _fetch_from_api(self) -> Optional[Dict[str, ModelPricingData]]:
        """Fetch pricing from Models.dev API.

        Returns:
            Parsed pricing data or None on failure
        """
        if not HAS_REQUESTS:
            return None

        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return self._parse_api_response(data)

        except (requests.RequestException, json.JSONDecodeError, ValueError):
            return None

    def _parse_api_response(self, data: Dict[str, Any]) -> Dict[str, ModelPricingData]:
        """Parse Models.dev API response.

        The API returns providers with nested models structure:
        {
            "provider-id": {
                "id": "provider-id",
                "models": {
                    "model-id": {
                        "id": "model-id",
                        "cost": {"input": 0.003, "output": 0.015},
                        "limit": {"context": 200000, "output": 8192}
                    }
                }
            }
        }

        Args:
            data: Raw API response

        Returns:
            Dict of model_id -> ModelPricingData
        """
        pricing = {}

        for provider_id, provider_info in data.items():
            if not isinstance(provider_info, dict):
                continue

            # Get models from provider
            models = provider_info.get("models", {})
            if not isinstance(models, dict):
                continue

            for model_id, model_info in models.items():
                if not isinstance(model_info, dict):
                    continue

                try:
                    # Extract cost from nested structure
                    cost = model_info.get("cost", {})
                    limit = model_info.get("limit", {})

                    input_price = self._extract_price(cost, ["input"])
                    output_price = self._extract_price(cost, ["output"])
                    cache_read = self._extract_price(cost, ["cache_read", "cacheRead"])
                    cache_write = self._extract_price(cost, ["cache_write", "cacheWrite"])
                    context = limit.get("context", 200000)

                    pricing[model_id] = ModelPricingData(
                        input_price=input_price,
                        output_price=output_price,
                        cache_read_price=cache_read,
                        cache_write_price=cache_write,
                        context_window=int(context) if context else 200000,
                    )

                    # Also add normalized version of model name
                    normalized = self._normalize_model_name(model_id)
                    if normalized != model_id and normalized not in pricing:
                        pricing[normalized] = pricing[model_id]

                    # Add with provider prefix for disambiguation
                    full_id = f"{provider_id}/{model_id}"
                    pricing[full_id] = pricing[model_id]

                except (ValueError, TypeError):
                    continue

        return pricing

    def _extract_price(
        self,
        data: Dict[str, Any],
        keys: list,
    ) -> Decimal:
        """Extract price from data using multiple possible keys.

        Args:
            data: Model data dict
            keys: List of possible key names

        Returns:
            Price as Decimal
        """
        for key in keys:
            if key in data and data[key] is not None:
                value = data[key]
                # Handle per-token pricing (convert to per-million)
                if isinstance(value, (int, float)) and value < 0.01:
                    value = value * 1_000_000
                return Decimal(str(value))
        return Decimal("0")

    def _normalize_model_name(self, model_id: str) -> str:
        """Normalize model name for matching.

        Args:
            model_id: Raw model ID

        Returns:
            Normalized model name
        """
        import re
        model_id = model_id.lower()

        # Strip date suffixes
        model_id = re.sub(r"-\d{8}$", "", model_id)

        # Normalize version separators
        model_id = re.sub(
            r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)",
            r"claude-\1-\2.\3",
            model_id,
        )

        return model_id

    def get_model_pricing(self, model_id: str) -> Optional[ModelPricingData]:
        """Get pricing for a specific model.

        Args:
            model_id: Model identifier

        Returns:
            ModelPricingData or None if not found
        """
        pricing = self.fetch_pricing()

        # Try exact match
        if model_id in pricing:
            return pricing[model_id]

        # Try normalized match
        normalized = self._normalize_model_name(model_id)
        if normalized in pricing:
            return pricing[normalized]

        # Try prefix matching
        for key in pricing:
            if key.startswith(normalized) or normalized.startswith(key):
                return pricing[key]

        return None

    def clear_cache(self) -> None:
        """Clear all cached pricing data."""
        self._cached_data = None
        self._cache_time = None

        if self.cache_path.exists():
            try:
                self.cache_path.unlink()
            except OSError:
                pass

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache status information.

        Returns:
            Dict with cache info
        """
        info = {
            "api_url": self.api_url,
            "cache_path": str(self.cache_path),
            "cache_ttl_hours": self.cache_ttl.total_seconds() / 3600,
            "memory_cached": self._cached_data is not None,
            "memory_cache_age": None,
            "file_cache_exists": self.cache_path.exists(),
            "file_cache_age": None,
            "models_count": 0,
        }

        if self._cache_time:
            info["memory_cache_age"] = (datetime.now() - self._cache_time).total_seconds()

        if self.cache_path.exists():
            try:
                mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime)
                info["file_cache_age"] = (datetime.now() - mtime).total_seconds()

                with open(self.cache_path, "r") as f:
                    cache_data = json.load(f)
                    info["models_count"] = len(cache_data.get("models", {}))
            except (OSError, json.JSONDecodeError):
                pass

        return info
