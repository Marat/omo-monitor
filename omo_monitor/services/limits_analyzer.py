"""Limits analysis service for OpenCode Monitor.

Analyzes usage against subscription limits with rolling time windows.
"""

import fnmatch
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from decimal import Decimal
from collections import defaultdict
from pathlib import Path

from ..models.session import SessionData, InteractionFile
from ..models.limits import (
    LimitsConfig,
    ProviderLimit,
    ModelLimit,
    ProviderUsageWindow,
    LimitsReport,
    OptimizationSuggestion,
    OptimizationReport,
)
from ..config import ModelPricing


# Known model mappings for routing recommendations
# Maps provider_id -> list of model patterns/names
PROVIDER_MODEL_MAPPING = {
    # Anthropic MAX - Claude models directly
    "anthropic": [
        "claude-opus-4-5",
        "claude-opus-4-5-thinking",
        "claude-opus-4.5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-thinking",
        "claude-sonnet-4.5",
        "claude-haiku-*",
        "claude-3-*",
    ],
    # Antigravity (via google provider) - Claude + Gemini
    "google": [
        # Claude via Antigravity
        "antigravity-claude-opus-4-5-thinking",
        "antigravity-claude-sonnet-4-5-thinking",
        "antigravity-claude-sonnet-4-5",
        # Gemini 3 Pro variants
        "antigravity-gemini-3-pro-high",
        "antigravity-gemini-3-pro",
        "antigravity-gemini-3-pro-low",
        "antigravity-gemini-3-pro-image",
        "antigravity-gemini-3-pro-preview",
        # Gemini 3 Flash
        "antigravity-gemini-3-flash",
    ],
    # OpenAI - GPT and o-series
    "openai": [
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5.1-codex-max",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4-turbo",
        "o1",
        "o1-preview",
        "o1-mini",
        "o3",
        "o3-mini",
        "o4-mini",
    ],
    # MiniMax
    "minimax": [
        "MiniMax-M2.1",
        "minimax-m2.1",
        "MiniMax-M2",
        "abab6.5-chat",
    ],
    # Z.AI (ZhiPu) - GLM models
    "zai": [
        "glm-4.7",
        "glm-4.6",
        "glm-4.5",
        "glm-4.7-free",
        "codegeex-4",
        "chatglm-turbo",
    ],
    # Legacy provider_id support
    "zai-coding-plan": [
        "glm-4.7",
        "glm-4.6",
        "glm-4.7-free",
    ],
    # DeepSeek
    "deepseek": [
        "deepseek-coder-v2",
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    # Qwen (Alibaba)
    "qwen": [
        "qwen2.5-coder",
        "qwen2.5-72b",
        "qwen-coder-turbo",
    ],
    # GitHub Copilot
    "github-copilot": [
        "copilot-chat",
        "copilot-completion",
    ],
    # OpenRouter (aggregator)
    "openrouter": [
        # Can route to any model
    ],
    # Cursor
    "cursor": [
        "cursor-fast",
        "cursor-small",
    ],
}

# Antigravity model alternatives for each capability level
# Based on actual available models from Account-Manager
# Format: key -> "provider/model-name" for oh-my-opencode.json
ANTIGRAVITY_MODELS = {
    # Claude models via Antigravity (250 req per account)
    # NOTE: Opus has DAILY limit (24h), Sonnet has 5h limit
    "claude_opus_thinking": "google/antigravity-claude-opus-4-5-thinking",  # Opus with thinking
    "claude_sonnet_thinking": "google/antigravity-claude-sonnet-4-5-thinking",  # Sonnet with thinking
    "claude_sonnet": "google/antigravity-claude-sonnet-4-5",  # Sonnet standard
    # Gemini 3 Pro variants (400 req/5h per account)
    "gemini_pro_high": "google/antigravity-gemini-3-pro-high",
    "gemini_pro": "google/antigravity-gemini-3-pro",
    "gemini_pro_low": "google/antigravity-gemini-3-pro-low",
    "gemini_pro_image": "google/antigravity-gemini-3-pro-image",
    "gemini_pro_preview": "google/antigravity-gemini-3-pro-preview",
    # Gemini Flash (3000 req/5h per account)
    "gemini_flash": "google/antigravity-gemini-3-flash",
}

# Alternative provider models for routing optimization
# Maps capability level -> (provider, model, description)
ALTERNATIVE_MODELS = {
    # High-capability alternatives (for complex tasks)
    "high": [
        ("anthropic", "claude-sonnet-4-5-thinking", "Anthropic direct - unlimited"),
        (
            "google",
            "antigravity-claude-sonnet-4-5-thinking",
            "Antigravity Claude - 2500/5h",
        ),
        ("openai", "gpt-5.2", "OpenAI GPT-5.2"),
    ],
    # Medium-capability alternatives
    "medium": [
        ("google", "antigravity-gemini-3-pro-high", "Antigravity Gemini Pro - 4000/5h"),
        ("zai", "glm-4.7", "Z.AI GLM-4.7 - 800M tok/5h"),
        ("minimax", "MiniMax-M2.1", "MiniMax - 500M tok/day"),
    ],
    # Fast/cheap alternatives (for utility tasks)
    "fast": [
        ("google", "antigravity-gemini-3-flash", "Antigravity Flash - 30000/5h"),
        ("zai", "glm-4.7-free", "Z.AI free tier"),
        ("deepseek", "deepseek-chat", "DeepSeek cheap"),
    ],
}

# Capacity with 10 accounts (NOTE: different windows!)
ANTIGRAVITY_CAPACITY = {
    # Claude Opus: 250 × 10 = 2500/DAY (24h window)
    "claude_opus_thinking": {"requests": 2500, "window_hours": 24},
    # Claude Sonnet: 250 × 10 = 2500/5h
    "claude_sonnet_thinking": {"requests": 2500, "window_hours": 5},
    "claude_sonnet": {"requests": 2500, "window_hours": 5},
    # Gemini Pro variants: 400 × 10 = 4000/5h
    "gemini_pro_high": {"requests": 4000, "window_hours": 5},
    "gemini_pro": {"requests": 4000, "window_hours": 5},
    "gemini_pro_low": {"requests": 4000, "window_hours": 5},
    "gemini_pro_image": {"requests": 4000, "window_hours": 5},
    "gemini_pro_preview": {"requests": 4000, "window_hours": 5},
    # Gemini Flash: 3000 × 10 = 30000/5h
    "gemini_flash": {"requests": 30000, "window_hours": 5},
}


def get_antigravity_recommendation(
    avg_tokens_per_req: int, task_type: str = "general"
) -> tuple[str, str, str]:
    """Get recommended Antigravity model based on task complexity.

    Args:
        avg_tokens_per_req: Average tokens per request
        task_type: Type of task (planning, coding, review, etc.)

    Returns:
        Tuple of (model_key, full_model_path, reason)
    """
    # For very complex tasks (>100K tok/req), use Opus Thinking
    # Note: Opus has DAILY limit (2500/day), not 5h!
    if avg_tokens_per_req > 100000:
        cap = ANTIGRAVITY_CAPACITY["claude_opus_thinking"]
        return (
            "claude_opus_thinking",
            ANTIGRAVITY_MODELS["claude_opus_thinking"],
            f"Very high complexity ({avg_tokens_per_req:,} tok/req) -> Opus Thinking [{cap['requests']}/day]",
        )
    # For complex tasks (80-100K tok/req), use Claude Sonnet Thinking
    elif avg_tokens_per_req > 80000:
        cap = ANTIGRAVITY_CAPACITY["claude_sonnet_thinking"]
        return (
            "claude_sonnet_thinking",
            ANTIGRAVITY_MODELS["claude_sonnet_thinking"],
            f"High complexity ({avg_tokens_per_req:,} tok/req) -> Sonnet Thinking [{cap['requests']}/{cap['window_hours']}h]",
        )
    # For medium-high tasks (50-80K tok/req), use Gemini Pro High
    elif avg_tokens_per_req > 50000:
        cap = ANTIGRAVITY_CAPACITY["gemini_pro_high"]
        return (
            "gemini_pro_high",
            ANTIGRAVITY_MODELS["gemini_pro_high"],
            f"Medium-high ({avg_tokens_per_req:,} tok/req) -> Gemini Pro High [{cap['requests']}/{cap['window_hours']}h]",
        )
    # For medium tasks (30-50K tok/req), use Gemini Pro
    elif avg_tokens_per_req > 30000:
        cap = ANTIGRAVITY_CAPACITY["gemini_pro"]
        return (
            "gemini_pro",
            ANTIGRAVITY_MODELS["gemini_pro"],
            f"Medium ({avg_tokens_per_req:,} tok/req) -> Gemini Pro [{cap['requests']}/{cap['window_hours']}h]",
        )
    # For lower complexity tasks, use Gemini Flash (massive capacity)
    else:
        cap = ANTIGRAVITY_CAPACITY["gemini_flash"]
        return (
            "gemini_flash",
            ANTIGRAVITY_MODELS["gemini_flash"],
            f"Lower ({avg_tokens_per_req:,} tok/req) -> Gemini Flash [{cap['requests']}/{cap['window_hours']}h]",
        )


def get_provider_models(provider_id: str) -> List[str]:
    """Get list of known models for a provider.

    Args:
        provider_id: Provider identifier

    Returns:
        List of model names/patterns for this provider
    """
    return PROVIDER_MODEL_MAPPING.get(provider_id, [])


def get_all_providers() -> List[str]:
    """Get list of all known provider IDs.

    Returns:
        List of provider identifiers
    """
    return list(PROVIDER_MODEL_MAPPING.keys())


class LimitsAnalyzer:
    """Service for analyzing usage against subscription limits."""

    def __init__(
        self,
        limits_config: Optional[LimitsConfig],
        pricing_data: dict[str, ModelPricing],
    ):
        """Initialize limits analyzer.

        Args:
            limits_config: Subscription limits configuration (can be None)
            pricing_data: Model pricing information
        """
        self.limits_config = limits_config
        self.pricing_data = pricing_data

    def analyze_limits(
        self,
        sessions: List[SessionData],
        reference_time: Optional[datetime] = None,
        window_hours_override: Optional[int] = None,
    ) -> LimitsReport:
        """Analyze usage against subscription limits.

        Args:
            sessions: All sessions to analyze
            reference_time: Reference time for window calculations (default: now)
            window_hours_override: Override window hours for ALL providers (ignores config)

        Returns:
            LimitsReport with usage vs limits for each provider
        """
        if reference_time is None:
            reference_time = datetime.now()

        # Collect all interactions across sessions
        all_interactions: List[tuple[InteractionFile, str]] = []  # (file, session_id)
        for session in sessions:
            for file in session.files:
                all_interactions.append((file, session.session_id))

        # Group by provider
        provider_interactions: dict[str, List[InteractionFile]] = defaultdict(list)
        all_providers_seen: set[str] = set()

        for interaction, _ in all_interactions:
            provider_id = interaction.provider_id or "unknown"
            all_providers_seen.add(provider_id)
            provider_interactions[provider_id].append(interaction)

        # Analyze each configured provider
        provider_usage_list: List[ProviderUsageWindow] = []
        configured_provider_ids: set[str] = set()

        if self.limits_config:
            for provider_limit in self.limits_config.providers:
                configured_provider_ids.add(provider_limit.provider_id)

                usage = self._analyze_provider_window(
                    provider_limit,
                    provider_interactions.get(provider_limit.provider_id, []),
                    reference_time,
                    window_hours_override,
                )
                provider_usage_list.append(usage)

        # Identify unconfigured providers (have usage but no limits set)
        unconfigured = list(all_providers_seen - configured_provider_ids - {"unknown"})

        # Generate recommendations
        recommendations = self._generate_recommendations(provider_usage_list)

        return LimitsReport(
            generated_at=reference_time,
            window_end=reference_time,
            provider_usage=provider_usage_list,
            unconfigured_providers=sorted(unconfigured),
            recommendations=recommendations,
        )

    def _analyze_provider_window(
        self,
        provider_limit: ProviderLimit,
        interactions: List[InteractionFile],
        reference_time: datetime,
        window_hours_override: Optional[int] = None,
    ) -> ProviderUsageWindow:
        """Analyze usage for a single provider within its time window.

        Args:
            provider_limit: Provider's configured limits
            interactions: All interactions for this provider
            reference_time: Reference time for window
            window_hours_override: Override window hours (ignores provider config)

        Returns:
            ProviderUsageWindow with usage statistics
        """
        # Use override if provided, otherwise use provider's configured window
        window_hours = (
            window_hours_override
            if window_hours_override is not None
            else provider_limit.window_hours
        )
        window_start = reference_time - timedelta(hours=window_hours)

        # Filter interactions within window
        window_interactions: List[InteractionFile] = []
        for interaction in interactions:
            if interaction.time_data and interaction.time_data.created_datetime:
                if interaction.time_data.created_datetime >= window_start:
                    window_interactions.append(interaction)

        # Calculate usage (use total tokens for accurate workload)
        requests_used = len(window_interactions)
        tokens_used = sum(i.tokens.total for i in window_interactions)

        # Calculate cost
        cost_used = Decimal("0.0")
        for interaction in window_interactions:
            cost_used += interaction.calculate_cost(self.pricing_data)

        # Track models used
        models_used: dict[str, int] = defaultdict(int)
        for interaction in window_interactions:
            models_used[interaction.model_id] += 1

        # Calculate effective limits (accounting for multi-account)
        requests_limit = provider_limit.effective_requests_per_window
        tokens_limit = provider_limit.effective_tokens_per_window

        # If model-specific limits exist, calculate aggregate
        if provider_limit.model_limits and not requests_limit:
            # Sum up model-specific limits as an approximation
            total_model_requests = 0
            for model_limit in provider_limit.model_limits:
                if model_limit.requests_per_window:
                    total_model_requests += (
                        model_limit.requests_per_window * provider_limit.account_count
                    )
            if total_model_requests > 0:
                requests_limit = total_model_requests

        return ProviderUsageWindow(
            provider_id=provider_limit.provider_id,
            display_name=provider_limit.display_name,
            window_hours=window_hours,
            window_start=window_start,
            window_end=reference_time,
            requests_used=requests_used,
            tokens_used=tokens_used,
            cost_used=cost_used,
            requests_limit=requests_limit,
            tokens_limit=tokens_limit,
            monthly_cost_limit=provider_limit.monthly_cost_limit,
            models_used=dict(models_used),
        )

    def _generate_recommendations(
        self, provider_usage: List[ProviderUsageWindow]
    ) -> List[str]:
        """Generate recommendations based on usage patterns.

        Args:
            provider_usage: List of provider usage windows

        Returns:
            List of recommendation strings
        """
        recommendations: List[str] = []

        # Find over-limit and under-utilized providers
        over_limit: List[ProviderUsageWindow] = []
        under_utilized: List[ProviderUsageWindow] = []

        for usage in provider_usage:
            if usage.is_over_limit:
                over_limit.append(usage)
            elif usage.requests_utilization is not None:
                if usage.requests_utilization < 30:
                    under_utilized.append(usage)

        # Generate redistribution recommendations
        if over_limit and under_utilized:
            over_names = ", ".join(u.display_name or u.provider_id for u in over_limit)
            under_names = ", ".join(
                u.display_name or u.provider_id for u in under_utilized
            )
            recommendations.append(
                f"Consider moving load from {over_names} to {under_names}"
            )

        # Specific recommendations for high utilization
        for usage in provider_usage:
            if usage.utilization_status == "warning":
                remaining = usage.requests_remaining
                if remaining is not None:
                    recommendations.append(
                        f"{usage.display_name or usage.provider_id}: "
                        f"Only {remaining:,} requests remaining in current {usage.window_hours}h window"
                    )

        return recommendations

    def analyze_model_limits(
        self,
        sessions: List[SessionData],
        provider_id: str,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Analyze usage by model for a specific provider with model-level limits.

        Args:
            sessions: Sessions to analyze
            provider_id: Provider to analyze
            reference_time: Reference time for window

        Returns:
            Dict of model_pattern -> usage stats
        """
        if reference_time is None:
            reference_time = datetime.now()

        if not self.limits_config:
            return {}

        provider_limit = self.limits_config.get_provider_limit(provider_id)
        if not provider_limit or not provider_limit.model_limits:
            return {}

        window_start = reference_time - timedelta(hours=provider_limit.window_hours)

        # Collect interactions for this provider within window
        model_usage: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "limit": None, "models_matched": []}
        )

        for session in sessions:
            for file in session.files:
                if file.provider_id != provider_id:
                    continue

                if file.time_data and file.time_data.created_datetime:
                    if file.time_data.created_datetime < window_start:
                        continue

                # Match to model limit pattern
                matched_pattern = None
                for model_limit in provider_limit.model_limits:
                    if fnmatch.fnmatch(file.model_id, model_limit.model_pattern):
                        matched_pattern = model_limit.model_pattern
                        if model_limit.requests_per_window:
                            model_usage[matched_pattern]["limit"] = (
                                model_limit.requests_per_window
                                * provider_limit.account_count
                            )
                        break

                if matched_pattern:
                    model_usage[matched_pattern]["requests"] += 1
                    model_usage[matched_pattern]["tokens"] += (
                        file.tokens.input + file.tokens.output
                    )
                    if (
                        file.model_id
                        not in model_usage[matched_pattern]["models_matched"]
                    ):
                        model_usage[matched_pattern]["models_matched"].append(
                            file.model_id
                        )

        return dict(model_usage)

    def generate_optimization_report(
        self,
        sessions: List[SessionData],
        hours: int = 24,
        reference_time: Optional[datetime] = None,
    ) -> OptimizationReport:
        """Generate optimization suggestions for load redistribution.

        Analyzes category-to-provider mapping and suggests which tasks
        could be moved to underutilized providers.

        Args:
            sessions: Sessions to analyze
            hours: Analysis period in hours
            reference_time: Reference time

        Returns:
            OptimizationReport with suggestions
        """
        if reference_time is None:
            reference_time = datetime.now()

        window_start = reference_time - timedelta(hours=hours)

        # Get current limits status
        limits_report = self.analyze_limits(sessions, reference_time)

        # Identify provider utilization
        overloaded = [
            p.provider_id
            for p in limits_report.provider_usage
            if p.utilization_status in ("over", "warning")
        ]
        underutilized = [
            p.provider_id
            for p in limits_report.provider_usage
            if p.requests_utilization is not None and p.requests_utilization < 50
        ]

        # Analyze category -> provider patterns
        category_provider_usage: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        total_requests = 0

        for session in sessions:
            for file in session.files:
                if file.time_data and file.time_data.created_datetime:
                    if file.time_data.created_datetime < window_start:
                        continue

                category = file.category or "uncategorized"
                provider = file.provider_id or "unknown"
                category_provider_usage[category][provider] += 1
                total_requests += 1

        # Generate suggestions
        suggestions: List[OptimizationSuggestion] = []
        requests_movable = 0

        # Look for categories using overloaded providers that could use underutilized ones
        for category, providers in category_provider_usage.items():
            for overloaded_provider in overloaded:
                if overloaded_provider in providers:
                    usage = providers[overloaded_provider]

                    # Suggest moving to underutilized providers
                    for target_provider in underutilized:
                        # Get potential target capacity
                        target_usage = next(
                            (
                                p
                                for p in limits_report.provider_usage
                                if p.provider_id == target_provider
                            ),
                            None,
                        )

                        if target_usage and target_usage.requests_remaining:
                            suggestions.append(
                                OptimizationSuggestion(
                                    category=category,
                                    current_provider=overloaded_provider,
                                    current_model="*",  # Generic
                                    suggested_provider=target_provider,
                                    suggested_model="*",
                                    reason=f"Category '{category}' uses {usage} req/window on overloaded {overloaded_provider}",
                                    potential_savings=f"~{usage} req freed from {overloaded_provider}",
                                )
                            )
                            requests_movable += usage
                            break  # One suggestion per category-provider pair

        return OptimizationReport(
            generated_at=reference_time,
            analysis_period_hours=hours,
            overloaded_providers=overloaded,
            underutilized_providers=underutilized,
            suggestions=suggestions,
            total_requests_analyzed=total_requests,
            requests_movable=requests_movable,
        )

    def get_provider_summary(
        self, sessions: List[SessionData], reference_time: Optional[datetime] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Get a simple summary of all provider usage.

        Args:
            sessions: Sessions to analyze
            reference_time: Reference time

        Returns:
            Dict of provider_id -> summary stats
        """
        if reference_time is None:
            reference_time = datetime.now()

        summary: dict[str, dict[str, Any]] = {}

        # Analyze limits for configured providers
        if self.limits_config:
            limits_report = self.analyze_limits(sessions, reference_time)

            for usage in limits_report.provider_usage:
                summary[usage.provider_id] = {
                    "display_name": usage.display_name,
                    "requests": usage.requests_used,
                    "tokens": usage.tokens_used,
                    "cost": float(usage.cost_used),
                    "requests_limit": usage.requests_limit,
                    "tokens_limit": usage.tokens_limit,
                    "requests_utilization": usage.requests_utilization,
                    "tokens_utilization": usage.tokens_utilization,
                    "status": usage.utilization_status,
                    "window_hours": usage.window_hours,
                    "models_used": usage.models_used,
                }

        return summary

    def analyze_agent_provider_usage(
        self,
        sessions: List[SessionData],
        hours: int = 24,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Analyze which agents use which providers and how much.

        Args:
            sessions: Sessions to analyze
            hours: Analysis window in hours
            reference_time: Reference time

        Returns:
            Dict of agent_name -> {provider_id -> {requests, tokens, avg_tokens}}
        """
        if reference_time is None:
            reference_time = datetime.now()

        window_start = reference_time - timedelta(hours=hours)

        # agent -> provider -> stats
        agent_provider_stats: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"requests": 0, "tokens": 0, "models": set()})
        )

        for session in sessions:
            for file in session.files:
                if file.time_data and file.time_data.created_datetime:
                    if file.time_data.created_datetime < window_start:
                        continue

                agent = file.agent or "unknown"
                provider = file.provider_id or "unknown"

                agent_provider_stats[agent][provider]["requests"] += 1
                # Use total tokens (includes cache) for accurate workload measurement
                agent_provider_stats[agent][provider]["tokens"] += file.tokens.total
                agent_provider_stats[agent][provider]["models"].add(file.model_id)

        # Convert sets to lists and calculate averages
        result: dict[str, dict[str, Any]] = {}
        for agent, providers in agent_provider_stats.items():
            result[agent] = {}
            for provider, stats in providers.items():
                result[agent][provider] = {
                    "requests": stats["requests"],
                    "tokens": stats["tokens"],
                    "avg_tokens": stats["tokens"] // stats["requests"]
                    if stats["requests"] > 0
                    else 0,
                    "models": list(stats["models"]),
                }

        return result

    def analyze_category_provider_usage(
        self,
        sessions: List[SessionData],
        hours: int = 24,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Analyze which categories use which providers.

        Args:
            sessions: Sessions to analyze
            hours: Analysis window in hours
            reference_time: Reference time

        Returns:
            Dict of category_name -> {provider_id -> {requests, tokens, avg_tokens}}
        """
        if reference_time is None:
            reference_time = datetime.now()

        window_start = reference_time - timedelta(hours=hours)

        # category -> provider -> stats
        cat_provider_stats: dict[str, dict[str, dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"requests": 0, "tokens": 0, "models": set()})
        )

        for session in sessions:
            for file in session.files:
                if file.time_data and file.time_data.created_datetime:
                    if file.time_data.created_datetime < window_start:
                        continue

                category = file.category or "uncategorized"
                provider = file.provider_id or "unknown"

                cat_provider_stats[category][provider]["requests"] += 1
                cat_provider_stats[category][provider]["tokens"] += file.tokens.total
                cat_provider_stats[category][provider]["models"].add(file.model_id)

        # Convert sets to lists and calculate averages
        result: dict[str, dict[str, Any]] = {}
        for category, providers in cat_provider_stats.items():
            result[category] = {}
            for provider, stats in providers.items():
                result[category][provider] = {
                    "requests": stats["requests"],
                    "tokens": stats["tokens"],
                    "avg_tokens": stats["tokens"] // stats["requests"]
                    if stats["requests"] > 0
                    else 0,
                    "models": list(stats["models"]),
                }

        return result

    def generate_routing_recommendations(
        self,
        sessions: List[SessionData],
        omo_config_path: Optional[str] = None,
        hours: int = 24,
        reference_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Generate specific routing recommendations based on usage patterns.

        Analyzes which agents/categories could be moved to underutilized providers.
        Considers:
        - Agent complexity (by avg tokens)
        - Category purpose (quick vs ultrabrain)
        - Utility agents (explore, librarian) - usually keep on cheap providers
        - Main orchestrators (Sisyphus) - need high capability

        Args:
            sessions: Sessions to analyze
            omo_config_path: Path to oh-my-opencode.json
            hours: Analysis window in hours
            reference_time: Reference time

        Returns:
            List of recommendation dicts
        """
        if reference_time is None:
            reference_time = datetime.now()

        recommendations: List[Dict[str, Any]] = []

        # Load oh-my-opencode config if available
        omo_config = self._load_omo_config(omo_config_path)

        # Get current limits status
        limits_report = self.analyze_limits(sessions, reference_time)

        # Find underutilized providers (especially Antigravity)
        underutilized_capacity: dict[str, int] = {}
        for usage in limits_report.provider_usage:
            if usage.requests_remaining and usage.requests_remaining > 100:
                underutilized_capacity[usage.provider_id] = usage.requests_remaining

        google_capacity = underutilized_capacity.get("google", 0)

        # Utility agents that should stay on cheap providers
        utility_agents = {"explore", "librarian", "multimodal-looker"}

        # High-value agents that need quality models
        premium_agents = {
            "Sisyphus",
            "oracle",
            "Prometheus (Planner)",
            "Metis (Plan Consultant)",
        }

        # Categories that need quality
        premium_categories = {"ultrabrain", "most-capable", "medium"}
        cheap_categories = {"quick", "boilerplate", "test-writing"}

        # =============== AGENT RECOMMENDATIONS ===============
        agent_usage = self.analyze_agent_provider_usage(sessions, hours, reference_time)
        expensive_providers = {"anthropic"}

        for agent, providers in agent_usage.items():
            for provider, stats in providers.items():
                # Skip utility agents - they're fine on cheap providers
                if agent in utility_agents:
                    continue

                # Only recommend for expensive providers with significant usage
                if provider not in expensive_providers or stats["requests"] < 10:
                    continue

                # Check if Antigravity has capacity
                if google_capacity < stats["requests"]:
                    continue

                avg_tokens = stats["avg_tokens"]

                # Get current model from config
                current_model = None
                if omo_config and "agents" in omo_config:
                    agent_config = omo_config["agents"].get(agent, {})
                    current_model = agent_config.get("model")

                # Determine recommendation based on agent type and complexity
                if agent in premium_agents:
                    # Premium agents need high-capability Antigravity models
                    if avg_tokens > 80000:
                        suggested_model = ANTIGRAVITY_MODELS["claude_opus_thinking"]
                        reason = f"Premium agent, high complexity ({avg_tokens:,} tok/req) -> Opus Thinking"
                    else:
                        suggested_model = ANTIGRAVITY_MODELS["claude_sonnet_thinking"]
                        reason = f"Premium agent ({avg_tokens:,} tok/req) -> Claude Sonnet Thinking"
                else:
                    # Regular agents - use complexity-based recommendation
                    _, suggested_model, reason = get_antigravity_recommendation(
                        avg_tokens
                    )

                impact = (
                    "high"
                    if stats["requests"] > 100
                    else "medium"
                    if stats["requests"] > 30
                    else "low"
                )

                recommendations.append(
                    {
                        "type": "agent",
                        "name": agent,
                        "current_provider": provider,
                        "current_model": current_model or f"{provider}/*",
                        "suggested_provider": "google",
                        "suggested_model": suggested_model,
                        "reason": reason,
                        "requests_moved": stats["requests"],
                        "tokens_moved": stats["tokens"],
                        "avg_tokens": avg_tokens,
                        "impact": impact,
                        "antigravity_capacity_remaining": google_capacity
                        - stats["requests"],
                    }
                )

        # =============== CATEGORY RECOMMENDATIONS ===============
        category_usage = self.analyze_category_provider_usage(
            sessions, hours, reference_time
        )

        for category, providers in category_usage.items():
            # Skip uncategorized
            if category == "uncategorized":
                continue

            for provider, stats in providers.items():
                # Only recommend for expensive providers with significant usage
                if provider not in expensive_providers or stats["requests"] < 5:
                    continue

                # Check if Antigravity has capacity
                if google_capacity < stats["requests"]:
                    continue

                avg_tokens = stats["avg_tokens"]

                # Get current model from config
                current_model = None
                if omo_config and "categories" in omo_config:
                    cat_config = omo_config["categories"].get(category, {})
                    current_model = cat_config.get("model")

                # Determine recommendation based on category purpose
                if category in premium_categories:
                    # Premium categories need high-capability models
                    if avg_tokens > 80000:
                        suggested_model = ANTIGRAVITY_MODELS["claude_opus_thinking"]
                        reason = f"Premium category '{category}' ({avg_tokens:,} tok/req) -> Opus Thinking"
                    else:
                        suggested_model = ANTIGRAVITY_MODELS["claude_sonnet_thinking"]
                        reason = f"Premium category '{category}' ({avg_tokens:,} tok/req) -> Claude Sonnet"
                elif category in cheap_categories:
                    # Cheap categories can use Flash
                    suggested_model = ANTIGRAVITY_MODELS["gemini_flash"]
                    reason = f"Quick category '{category}' ({avg_tokens:,} tok/req) -> Gemini Flash"
                else:
                    # Use complexity-based recommendation
                    _, suggested_model, reason = get_antigravity_recommendation(
                        avg_tokens
                    )
                    reason = f"Category '{category}': {reason}"

                impact = (
                    "high"
                    if stats["requests"] > 50
                    else "medium"
                    if stats["requests"] > 20
                    else "low"
                )

                recommendations.append(
                    {
                        "type": "category",
                        "name": category,
                        "current_provider": provider,
                        "current_model": current_model or f"{provider}/*",
                        "suggested_provider": "google",
                        "suggested_model": suggested_model,
                        "reason": reason,
                        "requests_moved": stats["requests"],
                        "tokens_moved": stats["tokens"],
                        "avg_tokens": avg_tokens,
                        "impact": impact,
                        "antigravity_capacity_remaining": google_capacity
                        - stats["requests"],
                    }
                )

        # Sort by impact (high first) and requests moved
        impact_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(
            key=lambda x: (impact_order.get(x["impact"], 3), -x["requests_moved"])
        )

        return recommendations

    def _load_omo_config(
        self, config_path: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load oh-my-opencode configuration file.

        Args:
            config_path: Optional explicit path

        Returns:
            Parsed config dict or None
        """
        if config_path is None:
            # Try standard locations
            search_paths = [
                os.path.expanduser("~/.config/opencode/oh-my-opencode.json"),
                "oh-my-opencode.json",
            ]
            for path in search_paths:
                if os.path.exists(path):
                    config_path = path
                    break

        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return None

    def apply_routing_recommendations(
        self,
        recommendations: List[Dict[str, Any]],
        omo_config_path: Optional[str] = None,
        dry_run: bool = True,
    ) -> Tuple[Dict[str, Any], str]:
        """Apply routing recommendations to oh-my-opencode config.

        Args:
            recommendations: List of recommendations to apply
            omo_config_path: Path to config file
            dry_run: If True, return changes without writing

        Returns:
            Tuple of (modified_config, summary_message)
        """
        if omo_config_path is None:
            omo_config_path = os.path.expanduser(
                "~/.config/opencode/oh-my-opencode.json"
            )

        config = self._load_omo_config(omo_config_path)
        if not config:
            return {}, "Error: Could not load oh-my-opencode.json"

        changes: List[str] = []

        for rec in recommendations:
            if rec["type"] == "agent" and rec["name"] in config.get("agents", {}):
                old_model = config["agents"][rec["name"]].get("model", "not set")
                config["agents"][rec["name"]]["model"] = rec["suggested_model"]
                changes.append(
                    f"Agent '{rec['name']}': {old_model} -> {rec['suggested_model']}"
                )

            elif rec["type"] == "category" and rec["name"] in config.get(
                "categories", {}
            ):
                old_model = config["categories"][rec["name"]].get("model", "not set")
                config["categories"][rec["name"]]["model"] = rec["suggested_model"]
                changes.append(
                    f"Category '{rec['name']}': {old_model} -> {rec['suggested_model']}"
                )

        summary = f"Changes to apply ({len(changes)} modifications):\n" + "\n".join(
            f"  - {c}" for c in changes
        )

        if not dry_run and changes:
            # Backup existing config
            backup_path = (
                omo_config_path + f".bak.{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
            )
            try:
                import shutil

                shutil.copy2(omo_config_path, backup_path)

                with open(omo_config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)

                summary += f"\n\nConfig saved! Backup at: {backup_path}"
            except IOError as e:
                summary += f"\n\nError saving config: {e}"
        elif dry_run:
            summary += "\n\n[DRY RUN - no changes written]"

        return config, summary
