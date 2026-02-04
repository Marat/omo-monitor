"""Pricing provider abstraction.

Provides unified interface for model pricing from multiple sources:
- Local: models.json file (existing)
- Models.dev: Online API
- Both: Combined with fallback
"""

from decimal import Decimal
from typing import Dict, Optional, Any, TYPE_CHECKING

from .models_dev import ModelsDevClient, ModelPricingData

if TYPE_CHECKING:
    from ..config import ModelPricing


class PricingProvider:
    """Unified pricing provider with multiple sources."""

    def __init__(
        self,
        source: str = "local",
        fallback_to_local: bool = True,
        cache_ttl_hours: int = 24,
        api_url: Optional[str] = None,
    ):
        """Initialize pricing provider.

        Args:
            source: Pricing source - "local", "models.dev", or "both"
            fallback_to_local: Fall back to local if API fails
            cache_ttl_hours: Cache TTL for Models.dev
            api_url: Override Models.dev API URL
        """
        self.source = source
        self.fallback_to_local = fallback_to_local
        self._local_pricing: Optional[Dict[str, "ModelPricing"]] = None
        self._models_dev: Optional[ModelsDevClient] = None

        if source in ("models.dev", "both"):
            self._models_dev = ModelsDevClient(
                cache_ttl_hours=cache_ttl_hours,
                api_url=api_url,
            )

    def set_local_pricing(self, pricing_data: Dict[str, "ModelPricing"]) -> None:
        """Set local pricing data.

        Args:
            pricing_data: Dict of model_id -> ModelPricing from config
        """
        self._local_pricing = pricing_data

    def get_pricing(self, model_id: str) -> Optional[ModelPricingData]:
        """Get pricing for a model.

        Args:
            model_id: Model identifier

        Returns:
            ModelPricingData or None if not found
        """
        if self.source == "local":
            return self._get_local_pricing(model_id)

        elif self.source == "models.dev":
            pricing = self._get_models_dev_pricing(model_id)
            if pricing:
                return pricing
            if self.fallback_to_local:
                return self._get_local_pricing(model_id)
            return None

        else:  # "both"
            # Try local first (faster), then Models.dev for unknown models
            local = self._get_local_pricing(model_id)
            if local:
                return local
            return self._get_models_dev_pricing(model_id)

    def _get_local_pricing(self, model_id: str) -> Optional[ModelPricingData]:
        """Get pricing from local config.

        Args:
            model_id: Model identifier

        Returns:
            ModelPricingData or None
        """
        if not self._local_pricing:
            self._load_local_pricing()

        if not self._local_pricing:
            return None

        # Try exact match
        if model_id in self._local_pricing:
            return self._convert_local_pricing(self._local_pricing[model_id])

        # Try normalized match
        normalized = self._normalize_model_name(model_id)
        if normalized in self._local_pricing:
            return self._convert_local_pricing(self._local_pricing[normalized])

        # Try prefix matching
        for key, pricing in self._local_pricing.items():
            if key.startswith(normalized) or normalized.startswith(key):
                return self._convert_local_pricing(pricing)

        return None

    def _convert_local_pricing(self, pricing: "ModelPricing") -> ModelPricingData:
        """Convert local ModelPricing to ModelPricingData.

        Args:
            pricing: Local ModelPricing object

        Returns:
            ModelPricingData
        """
        return ModelPricingData(
            input_price=Decimal(str(pricing.input)),
            output_price=Decimal(str(pricing.output)),
            cache_read_price=Decimal(str(pricing.cache_read)),
            cache_write_price=Decimal(str(pricing.cache_write)),
            context_window=pricing.context_window,
            session_quota=Decimal(str(pricing.session_quota)),
        )

    def _get_models_dev_pricing(self, model_id: str) -> Optional[ModelPricingData]:
        """Get pricing from Models.dev.

        Args:
            model_id: Model identifier

        Returns:
            ModelPricingData or None
        """
        if not self._models_dev:
            return None
        return self._models_dev.get_model_pricing(model_id)

    def _load_local_pricing(self) -> None:
        """Load local pricing from config."""
        try:
            from ..config import config_manager
            self._local_pricing = config_manager.load_pricing_data()
        except ImportError:
            pass

    def _normalize_model_name(self, model_id: str) -> str:
        """Normalize model name for matching.

        Args:
            model_id: Raw model ID

        Returns:
            Normalized name
        """
        import re
        model_id = model_id.lower()
        model_id = re.sub(r"-\d{8}$", "", model_id)
        model_id = re.sub(
            r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)",
            r"claude-\1-\2.\3",
            model_id,
        )
        return model_id

    def get_all_pricing(self) -> Dict[str, ModelPricingData]:
        """Get all available pricing data.

        Returns:
            Dict of model_id -> ModelPricingData
        """
        all_pricing: Dict[str, ModelPricingData] = {}

        # Add local pricing
        if self._local_pricing:
            for model_id, pricing in self._local_pricing.items():
                all_pricing[model_id] = self._convert_local_pricing(pricing)

        # Add/override with Models.dev pricing
        if self._models_dev and self.source in ("models.dev", "both"):
            models_dev_pricing = self._models_dev.fetch_pricing()
            for model_id, pricing in models_dev_pricing.items():
                if model_id not in all_pricing or self.source == "models.dev":
                    all_pricing[model_id] = pricing

        return all_pricing

    def refresh_models_dev(self) -> bool:
        """Force refresh Models.dev pricing.

        Returns:
            True if refresh succeeded
        """
        # Create client if not exists
        if not self._models_dev:
            self._models_dev = ModelsDevClient()

        try:
            result = self._models_dev.fetch_pricing(force_refresh=True)
            return result is not None and len(result) > 0
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get provider status information.

        Returns:
            Status dict
        """
        status = {
            "source": self.source,
            "fallback_to_local": self.fallback_to_local,
            "local_models_count": len(self._local_pricing) if self._local_pricing else 0,
            "models_dev_enabled": self._models_dev is not None,
        }

        # Create client to check cache status even if not primary source
        if not self._models_dev:
            self._models_dev = ModelsDevClient()

        status["models_dev"] = self._models_dev.get_cache_info()

        return status

    def get_models_dev_client(self) -> ModelsDevClient:
        """Get Models.dev client (creates if needed).

        Returns:
            ModelsDevClient instance
        """
        if not self._models_dev:
            self._models_dev = ModelsDevClient()
        return self._models_dev


# Global provider instance
_provider: Optional[PricingProvider] = None


def get_pricing_provider(
    source: Optional[str] = None,
    fallback_to_local: bool = True,
    cache_ttl_hours: int = 24,
) -> PricingProvider:
    """Get or create global pricing provider.

    Args:
        source: Pricing source (uses config if None)
        fallback_to_local: Fall back to local if API fails
        cache_ttl_hours: Cache TTL for Models.dev

    Returns:
        PricingProvider instance
    """
    global _provider

    # Determine source from config if not specified
    if source is None:
        try:
            from ..config import config_manager
            pricing_config = getattr(config_manager.config, "pricing", None)
            if pricing_config:
                source = getattr(pricing_config, "source", "local")
                fallback_to_local = getattr(pricing_config, "fallback_to_local", True)
                cache_ttl_hours = getattr(pricing_config, "cache_ttl_hours", 24)
            else:
                source = "local"
        except ImportError:
            source = "local"

    # Create or update provider
    if _provider is None or _provider.source != source:
        _provider = PricingProvider(
            source=source,
            fallback_to_local=fallback_to_local,
            cache_ttl_hours=cache_ttl_hours,
        )

    return _provider


def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """Calculate cost for token usage.

    Args:
        model_id: Model identifier
        input_tokens: Input token count
        output_tokens: Output token count
        cache_read_tokens: Cache read token count
        cache_write_tokens: Cache write token count

    Returns:
        Total cost in USD
    """
    provider = get_pricing_provider()
    pricing = provider.get_pricing(model_id)

    if not pricing:
        return Decimal("0")

    million = Decimal("1000000")
    cost = Decimal("0")

    cost += (Decimal(input_tokens) / million) * pricing.input
    cost += (Decimal(output_tokens) / million) * pricing.output
    cost += (Decimal(cache_read_tokens) / million) * pricing.cache_read
    cost += (Decimal(cache_write_tokens) / million) * pricing.cache_write

    return cost
