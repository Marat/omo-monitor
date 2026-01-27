"""Session data models for OpenCode Monitor."""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field, field_validator, ConfigDict


class TokenUsage(BaseModel):
    """Model for token usage data."""

    input: int = Field(default=0, ge=0)
    output: int = Field(default=0, ge=0)
    cache_write: int = Field(default=0, ge=0)
    cache_read: int = Field(default=0, ge=0)
    reasoning: int = Field(
        default=0, ge=0, description="Reasoning tokens (for o1/o3 models)"
    )

    @computed_field
    @property
    def total(self) -> int:
        """Calculate total tokens (excludes reasoning as it's internal)."""
        return self.input + self.output + self.cache_write + self.cache_read


class TimeData(BaseModel):
    """Model for timing information."""

    created: Optional[int] = Field(
        default=None, description="Creation timestamp in milliseconds"
    )
    completed: Optional[int] = Field(
        default=None, description="Completion timestamp in milliseconds"
    )

    @computed_field
    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate duration in milliseconds."""
        if self.created is not None and self.completed is not None:
            return self.completed - self.created
        return None

    @computed_field
    @property
    def created_datetime(self) -> Optional[datetime]:
        """Get creation time as datetime object."""
        if self.created is not None:
            return datetime.fromtimestamp(self.created / 1000)
        return None

    @computed_field
    @property
    def completed_datetime(self) -> Optional[datetime]:
        """Get completion time as datetime object."""
        if self.completed is not None:
            return datetime.fromtimestamp(self.completed / 1000)
        return None


class MessageSummary(BaseModel):
    """Model for message summary data (user messages)."""

    title: Optional[str] = Field(
        default=None, description="Summary title of the conversation"
    )
    diffs: List[str] = Field(default_factory=list, description="List of file diffs")


class ToolsConfig(BaseModel):
    """Model for available tools configuration (user messages)."""

    task: bool = Field(default=False, description="Task tool availability")
    delegate_task: bool = Field(
        default=False, description="Delegate task tool availability"
    )
    call_omo_agent: bool = Field(
        default=False, description="OMO agent tool availability"
    )


class InteractionFile(BaseModel):
    """Model for a single OpenCode interaction file.

    Covers all fields from OpenCode JSON format for both user and assistant messages.
    """

    # === Basic identification ===
    file_path: Path
    session_id: str
    message_id: Optional[str] = Field(
        default=None, description="Message ID from OpenCode"
    )
    role: str = Field(
        default="assistant", description="Message role: user or assistant"
    )
    parent_id: Optional[str] = Field(
        default=None, description="Parent message ID for threading"
    )

    # === Model & Provider ===
    model_id: str = Field(default="unknown", description="Model ID (normalized)")
    model_id_raw: Optional[str] = Field(
        default=None, description="Original model ID before normalization"
    )
    provider_id: Optional[str] = Field(
        default=None,
        description="Provider ID (e.g., anthropic, openai, zai-coding-plan)",
    )

    # === Token usage ===
    tokens: TokenUsage = Field(default_factory=TokenUsage)

    # === Timing ===
    time_data: Optional[TimeData] = Field(default=None)

    # === Cost ===
    cost: Optional[Decimal] = Field(
        default=None, description="Cost reported by OpenCode (may be 0)"
    )

    # === Agent & Category (oh-my-opencode) ===
    agent: Optional[str] = Field(
        default=None, description="Agent name (e.g., explore, oracle, Sisyphus)"
    )
    mode: Optional[str] = Field(
        default=None, description="Agent mode (usually same as agent)"
    )
    category: Optional[str] = Field(
        default=None, description="Delegate task category (e.g., bugfix, algorithm)"
    )
    skills: List[str] = Field(
        default_factory=list,
        description="Skills used in delegate_task (e.g., playwright, git-master)",
    )

    # === Project paths ===
    project_path: Optional[str] = Field(
        default=None, description="Project working directory (cwd)"
    )
    root_path: Optional[str] = Field(default=None, description="Project root path")

    # === Completion info (assistant messages) ===
    finish_reason: Optional[str] = Field(
        default=None, description="How the response finished (tool-calls, stop, etc.)"
    )

    # === User message specific ===
    summary: Optional[MessageSummary] = Field(
        default=None, description="Message summary (user messages)"
    )
    system_prompt: Optional[str] = Field(
        default=None, description="System prompt (user messages, usually large)"
    )
    tools_config: Optional[ToolsConfig] = Field(
        default=None, description="Available tools configuration (user messages)"
    )

    # === Raw data for future extensibility ===
    raw_data: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v):
        """Ensure file path is a Path object."""
        return Path(v) if not isinstance(v, Path) else v

    @computed_field
    @property
    def file_name(self) -> str:
        """Get the file name."""
        return self.file_path.name

    @computed_field
    @property
    def modification_time(self) -> datetime:
        """Get file modification time."""
        return datetime.fromtimestamp(self.file_path.stat().st_mtime)

    @computed_field
    @property
    def project_name(self) -> str:
        """Get project name from project path."""
        if not self.project_path:
            return "Unknown"
        return Path(self.project_path).name if self.project_path else "Unknown"

    def calculate_cost(self, pricing_data: Dict[str, Any]) -> Decimal:
        """Calculate cost for this interaction with flexible model name matching.

        Args:
            pricing_data: Dictionary of model pricing information

        Returns:
            Calculated cost in USD
        """
        pricing = None

        # First try exact match
        if self.model_id in pricing_data:
            pricing = pricing_data[self.model_id]
        else:
            # Try prefix matching - extract base model name
            # e.g., claude-opus-4.5-20251101 -> claude-opus-4.5
            from ..utils.file_utils import FileProcessor

            normalized = FileProcessor._normalize_model_name(self.model_id)

            if normalized in pricing_data:
                pricing = pricing_data[normalized]
            else:
                # Try finding a matching key by prefix
                for key in pricing_data.keys():
                    if normalized.startswith(key) or key.startswith(normalized):
                        # Check if they're similar (same model family)
                        # e.g., "claude-opus-4.5" matches "claude-opus-4.5-extended"
                        if (
                            key.replace("-extended", "") == normalized
                            or normalized.replace("-extended", "") == key
                        ):
                            pricing = pricing_data[key]
                            break

        if pricing is None:
            return Decimal("0.0")

        cost = Decimal("0.0")

        # Convert to cost per million tokens
        million = Decimal("1000000")

        cost += (Decimal(self.tokens.input) / million) * Decimal(str(pricing.input))
        cost += (Decimal(self.tokens.output) / million) * Decimal(str(pricing.output))
        cost += (Decimal(self.tokens.cache_write) / million) * Decimal(
            str(pricing.cache_write)
        )
        cost += (Decimal(self.tokens.cache_read) / million) * Decimal(
            str(pricing.cache_read)
        )

        return cost


class SessionData(BaseModel):
    """Model for a complete OpenCode session."""

    session_id: str
    session_path: Path
    files: List[InteractionFile] = Field(default_factory=list)
    session_title: Optional[str] = Field(
        default=None, description="Human-readable session title from OpenCode"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("session_path")
    @classmethod
    def validate_session_path(cls, v):
        """Ensure session path is a Path object."""
        return Path(v) if not isinstance(v, Path) else v

    @computed_field
    @property
    def models_used(self) -> List[str]:
        """Get list of unique models used in this session."""
        return list(set(file.model_id for file in self.files))

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total token usage for the session."""
        total = TokenUsage()
        for file in self.files:
            total.input += file.tokens.input
            total.output += file.tokens.output
            total.cache_write += file.tokens.cache_write
            total.cache_read += file.tokens.cache_read
        return total

    @computed_field
    @property
    def start_time(self) -> Optional[datetime]:
        """Get session start time (earliest file creation time)."""
        times = [
            file.time_data.created_datetime
            for file in self.files
            if file.time_data and file.time_data.created_datetime
        ]
        return min(times) if times else None

    @computed_field
    @property
    def end_time(self) -> Optional[datetime]:
        """Get session end time (latest file completion time)."""
        times = [
            file.time_data.completed_datetime
            for file in self.files
            if file.time_data and file.time_data.completed_datetime
        ]
        return max(times) if times else None

    @computed_field
    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate total session duration in milliseconds."""
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return None

    @computed_field
    @property
    def duration_hours(self) -> float:
        """Calculate session duration in hours."""
        if self.duration_ms:
            return self.duration_ms / (1000 * 60 * 60)
        return 0.0

    @computed_field
    @property
    def duration_percentage(self) -> float:
        """Calculate session duration as percentage of 5-hour maximum."""
        max_hours = 5.0
        return min(100.0, (self.duration_hours / max_hours) * 100.0)

    @computed_field
    @property
    def total_processing_time_ms(self) -> int:
        """Calculate total processing time across all files."""
        total = 0
        for file in self.files:
            if file.time_data and file.time_data.duration_ms:
                total += file.time_data.duration_ms
        return total

    def calculate_total_cost(self, pricing_data: Dict[str, Any]) -> Decimal:
        """Calculate total cost for the session."""
        costs = [file.calculate_cost(pricing_data) for file in self.files]
        return Decimal(sum(costs))

    def get_model_breakdown(
        self, pricing_data: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Get breakdown of usage and cost by model."""
        breakdown = {}

        for model in self.models_used:
            model_files = [f for f in self.files if f.model_id == model]
            model_tokens = TokenUsage()
            model_cost = Decimal("0.0")

            for file in model_files:
                model_tokens.input += file.tokens.input
                model_tokens.output += file.tokens.output
                model_tokens.cache_write += file.tokens.cache_write
                model_tokens.cache_read += file.tokens.cache_read
                model_cost += file.calculate_cost(pricing_data)

            breakdown[model] = {
                "files": len(model_files),
                "tokens": model_tokens,
                "cost": model_cost,
            }

        return breakdown

    @computed_field
    @property
    def interaction_count(self) -> int:
        """Get number of interactions (files) in this session."""
        return len(self.files)

    @property
    def non_zero_token_files(self) -> List[InteractionFile]:
        """Get files with non-zero token usage."""
        return [file for file in self.files if file.tokens.total > 0]

    @computed_field
    @property
    def project_name(self) -> str:
        """Get project name for this session based on most common project path."""
        if not self.files:
            return "Unknown"

        # Get project paths from files that have them
        project_paths = [f.project_path for f in self.files if f.project_path]

        if not project_paths:
            return "Unknown"

        # Use the most common project path (in case there are mixed paths)
        from collections import Counter

        most_common_path = Counter(project_paths).most_common(1)[0][0]

        return Path(most_common_path).name if most_common_path else "Unknown"

    @computed_field
    @property
    def display_title(self) -> str:
        """Get display-friendly session title, with fallback to session ID."""
        if self.session_title:
            # Truncate long titles for better display
            if len(self.session_title) > 50:
                return self.session_title[:47] + "..."
            return self.session_title

        # Fallback to session ID
        return self.session_id

    @computed_field
    @property
    def providers_used(self) -> List[str]:
        """Get list of unique providers used in this session."""
        providers = set()
        for file in self.files:
            if file.provider_id:
                providers.add(file.provider_id)
        return list(providers)

    @computed_field
    @property
    def agents_used(self) -> List[str]:
        """Get list of unique agents used in this session."""
        agents = set()
        for file in self.files:
            if file.agent:
                agents.add(file.agent)
        return list(agents)

    @computed_field
    @property
    def categories_used(self) -> List[str]:
        """Get list of unique categories used in this session."""
        categories = set()
        for file in self.files:
            if file.category:
                categories.add(file.category)
        return list(categories)

    @computed_field
    @property
    def skills_used(self) -> List[str]:
        """Get list of unique skills used in this session."""
        skills = set()
        for file in self.files:
            if file.skills:
                skills.update(file.skills)
        return list(skills)

    @computed_field
    @property
    def total_reasoning_tokens(self) -> int:
        """Get total reasoning tokens (for o1/o3 models)."""
        return sum(file.tokens.reasoning for file in self.files)

    @computed_field
    @property
    def total_cost_reported(self) -> Decimal:
        """Get total cost as reported by OpenCode (may be 0 for some providers)."""
        total = Decimal("0.0")
        for file in self.files:
            if file.cost:
                total += file.cost
        return total

    @computed_field
    @property
    def finish_reason_stats(self) -> Dict[str, int]:
        """Get statistics on finish reasons."""
        from collections import Counter

        reasons = [f.finish_reason for f in self.files if f.finish_reason]
        return dict(Counter(reasons))

    @computed_field
    @property
    def user_message_count(self) -> int:
        """Get count of user messages in this session."""
        return sum(1 for f in self.files if f.role == "user")

    @computed_field
    @property
    def assistant_message_count(self) -> int:
        """Get count of assistant messages in this session."""
        return sum(1 for f in self.files if f.role == "assistant")
