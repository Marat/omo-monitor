"""Subscription limits models for OpenCode Monitor."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field


class ModelLimit(BaseModel):
    """Limits for a specific model within a provider."""

    model_pattern: str = Field(
        description="Model name or pattern (e.g., 'claude-*', 'gemini-3-*')"
    )
    requests_per_window: Optional[int] = Field(
        default=None, description="Max requests per time window"
    )
    tokens_per_window: Optional[int] = Field(
        default=None, description="Max tokens per time window"
    )
    window_hours: Optional[int] = Field(
        default=None,
        description="Override window hours for this model (None = use provider default)",
    )


class ProviderLimit(BaseModel):
    """Subscription limits for a single provider/account."""

    provider_id: str = Field(
        description="Provider ID matching OpenCode's providerID field"
    )
    display_name: Optional[str] = Field(default=None, description="Human-readable name")

    # Time window in hours (default 5h for Antigravity-style rolling limits)
    window_hours: int = Field(default=5, description="Rolling time window in hours")

    # Account multiplier for multi-account setups (e.g., 10 Antigravity accounts)
    account_count: int = Field(
        default=1, description="Number of accounts (multiplies limits)"
    )

    # Provider-level limits (aggregated across all models)
    requests_per_window: Optional[int] = Field(
        default=None, description="Max requests per window per account"
    )
    tokens_per_window: Optional[int] = Field(
        default=None, description="Max tokens per window per account"
    )

    # Monthly cost limit (for subscription-based like Anthropic MAX)
    monthly_cost_limit: Optional[Decimal] = Field(
        default=None, description="Monthly cost budget in USD"
    )

    # Per-model limits within this provider
    model_limits: List[ModelLimit] = Field(
        default_factory=list, description="Per-model limits"
    )

    @computed_field
    @property
    def effective_requests_per_window(self) -> Optional[int]:
        """Total requests allowed considering account count."""
        if self.requests_per_window is None:
            return None
        return self.requests_per_window * self.account_count

    @computed_field
    @property
    def effective_tokens_per_window(self) -> Optional[int]:
        """Total tokens allowed considering account count."""
        if self.tokens_per_window is None:
            return None
        return self.tokens_per_window * self.account_count


class LimitsConfig(BaseModel):
    """Complete subscription limits configuration."""

    providers: List[ProviderLimit] = Field(default_factory=list)

    # Global defaults
    default_window_hours: int = Field(default=5, description="Default rolling window")

    def get_provider_limit(self, provider_id: str) -> Optional[ProviderLimit]:
        """Get limits for a specific provider."""
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        return None


class ProviderUsageWindow(BaseModel):
    """Usage statistics for a provider within a time window."""

    provider_id: str
    display_name: Optional[str] = None
    window_hours: int
    window_start: datetime
    window_end: datetime

    # Current usage
    requests_used: int = 0
    tokens_used: int = 0
    cost_used: Decimal = Field(default=Decimal("0.0"))

    # Limits (None = unlimited)
    requests_limit: Optional[int] = None
    tokens_limit: Optional[int] = None
    monthly_cost_limit: Optional[Decimal] = None

    # Per-model breakdown within window
    models_used: Dict[str, int] = Field(
        default_factory=dict, description="Model -> request count"
    )

    @computed_field
    @property
    def requests_utilization(self) -> Optional[float]:
        """Percentage of request limit used (0-100+)."""
        if self.requests_limit is None or self.requests_limit == 0:
            return None
        return (self.requests_used / self.requests_limit) * 100

    @computed_field
    @property
    def tokens_utilization(self) -> Optional[float]:
        """Percentage of token limit used (0-100+)."""
        if self.tokens_limit is None or self.tokens_limit == 0:
            return None
        return (self.tokens_used / self.tokens_limit) * 100

    @computed_field
    @property
    def requests_remaining(self) -> Optional[int]:
        """Remaining requests in window."""
        if self.requests_limit is None:
            return None
        return max(0, self.requests_limit - self.requests_used)

    @computed_field
    @property
    def tokens_remaining(self) -> Optional[int]:
        """Remaining tokens in window."""
        if self.tokens_limit is None:
            return None
        return max(0, self.tokens_limit - self.tokens_used)

    @computed_field
    @property
    def is_over_limit(self) -> bool:
        """Check if any limit is exceeded."""
        if self.requests_limit and self.requests_used > self.requests_limit:
            return True
        if self.tokens_limit and self.tokens_used > self.tokens_limit:
            return True
        return False

    @computed_field
    @property
    def utilization_status(self) -> str:
        """Return status based on highest utilization."""
        max_util = 0.0
        if self.requests_utilization is not None:
            max_util = max(max_util, self.requests_utilization)
        if self.tokens_utilization is not None:
            max_util = max(max_util, self.tokens_utilization)

        if max_util >= 100:
            return "over"
        elif max_util >= 80:
            return "warning"
        elif max_util >= 50:
            return "moderate"
        else:
            return "good"


class LimitsReport(BaseModel):
    """Complete limits analysis report."""

    generated_at: datetime
    window_end: datetime  # When the current rolling windows end

    # Per-provider usage within their respective windows
    provider_usage: List[ProviderUsageWindow] = Field(default_factory=list)

    # Providers with no configured limits (for awareness)
    unconfigured_providers: List[str] = Field(default_factory=list)

    # Recommendations
    recommendations: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def providers_over_limit(self) -> List[str]:
        """List of providers currently over their limits."""
        return [p.provider_id for p in self.provider_usage if p.is_over_limit]

    @computed_field
    @property
    def providers_warning(self) -> List[str]:
        """List of providers at >80% utilization."""
        return [
            p.provider_id
            for p in self.provider_usage
            if p.utilization_status == "warning"
        ]


class OptimizationSuggestion(BaseModel):
    """Suggestion for optimizing provider usage."""

    category: str  # Task category (e.g., "quick", "bugfix")
    current_provider: str
    current_model: str
    suggested_provider: str
    suggested_model: str
    reason: str
    potential_savings: Optional[str] = None  # e.g., "~500 req/5h freed"


class OptimizationReport(BaseModel):
    """Report with optimization suggestions for load redistribution."""

    generated_at: datetime
    analysis_period_hours: int

    # Current state
    overloaded_providers: List[str] = Field(default_factory=list)
    underutilized_providers: List[str] = Field(default_factory=list)

    # Suggestions
    suggestions: List[OptimizationSuggestion] = Field(default_factory=list)

    # Summary statistics
    total_requests_analyzed: int = 0
    requests_movable: int = 0  # Requests that could be moved to other providers
