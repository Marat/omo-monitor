"""Normalization utilities for providers and models.

Provides consistent naming for providers and models across different sources.
"""

import re
from typing import Dict, Optional


# Provider normalization mapping
# Maps various provider IDs/names to canonical provider names
PROVIDER_ALIASES: Dict[str, str] = {
    # Google Vertex with different model providers
    "google-vertex-anthropic": "anthropic",
    "google-vertex-ai": "google",
    "google-vertex": "google",
    "google-ai-studio": "google",
    "google-generative-ai": "google",

    # OpenAI variants
    "azure-openai": "openai",
    "azure": "openai",
    "openai-compatible": "openai",

    # Anthropic variants
    "anthropic-vertex": "anthropic",
    "bedrock-anthropic": "anthropic",
    "aws-bedrock": "anthropic",

    # Other mappings
    "deepseek-ai": "deepseek",
    "alibaba-cloud": "alibaba",
    "qwen": "alibaba",
    "mistralai": "mistral",
    "cohere": "cohere",
    "together": "together",
    "groq": "groq",
    "fireworks": "fireworks",

    # Proxy/aggregator services - keep original or map to underlying
    "302ai": "302ai",
    "zai-coding-plan": "zai-coding-plan",
    "antigravity": "antigravity",
    "fallback": "fallback",
}


def normalize_provider_id(provider_id: str) -> str:
    """Normalize provider ID to canonical form.

    Args:
        provider_id: Raw provider ID from any source

    Returns:
        Canonical provider ID
    """
    if not provider_id:
        return "unknown"

    provider_lower = provider_id.lower().strip()

    # Check direct alias mapping
    if provider_lower in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[provider_lower]

    # Check if provider_id contains a known provider name
    for alias, canonical in PROVIDER_ALIASES.items():
        if alias in provider_lower:
            return canonical

    return provider_lower


def infer_provider_from_model(model_id: str) -> str:
    """Infer provider ID from model name.

    Args:
        model_id: Model identifier (e.g., claude-opus-4-5-20251101)

    Returns:
        Canonical provider ID
    """
    if not model_id:
        return "unknown"

    model_lower = model_id.lower()

    # Claude models -> Anthropic
    if model_lower.startswith("claude"):
        return "anthropic"

    # OpenAI models
    if model_lower.startswith(("gpt", "o1-", "o3-", "o4-", "chatgpt")):
        return "openai"

    # Google models
    if model_lower.startswith(("gemini", "palm", "bison")):
        return "google"

    # DeepSeek
    if model_lower.startswith("deepseek"):
        return "deepseek"

    # Alibaba/Qwen
    if model_lower.startswith(("qwen", "qwq")):
        return "alibaba"

    # Mistral
    if model_lower.startswith(("mistral", "mixtral", "codestral", "pixtral")):
        return "mistral"

    # Meta/Llama
    if model_lower.startswith(("llama", "meta-llama")):
        return "meta"

    # Cohere
    if model_lower.startswith(("command", "cohere")):
        return "cohere"

    # Groq
    if "groq" in model_lower:
        return "groq"

    return "unknown"


def normalize_model_id(model_id: str) -> str:
    """Normalize model ID for pricing lookup.

    Removes date suffixes, normalizes version separators.

    Args:
        model_id: Raw model ID

    Returns:
        Normalized model ID
    """
    if not model_id:
        return "unknown"

    model_id = model_id.lower()

    # Strip date suffixes like -20250514, -20251101, @20251101
    model_id = re.sub(r"[-@]\d{8}$", "", model_id)

    # Normalize Claude version separators: claude-opus-4-5 -> claude-opus-4.5
    model_id = re.sub(
        r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)",
        r"claude-\1-\2.\3",
        model_id,
    )

    # Normalize GPT versions: gpt-4-1 -> gpt-4.1
    model_id = re.sub(
        r"gpt-(\d+)-(\d+)",
        r"gpt-\1.\2",
        model_id,
    )

    return model_id


def get_canonical_provider_model(
    provider_id: Optional[str],
    model_id: str,
) -> tuple[str, str]:
    """Get canonical provider and model IDs.

    Args:
        provider_id: Raw provider ID (may be None)
        model_id: Raw model ID

    Returns:
        Tuple of (canonical_provider, normalized_model)
    """
    normalized_model = normalize_model_id(model_id)

    if provider_id:
        canonical_provider = normalize_provider_id(provider_id)
    else:
        canonical_provider = infer_provider_from_model(model_id)

    return canonical_provider, normalized_model


def extract_provider_from_full_model_id(full_model_id: str) -> tuple[str, str]:
    """Extract provider and model from combined ID like 'provider/model'.

    Args:
        full_model_id: Model ID that may contain provider prefix

    Returns:
        Tuple of (provider_id, model_id)
    """
    if "/" in full_model_id:
        parts = full_model_id.split("/", 1)
        return normalize_provider_id(parts[0]), normalize_model_id(parts[1])

    return infer_provider_from_model(full_model_id), normalize_model_id(full_model_id)
