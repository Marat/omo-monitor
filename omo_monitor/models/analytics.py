"""Analytics data models for OpenCode Monitor."""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field
from collections import defaultdict
from .session import SessionData, TokenUsage


class DailyUsage(BaseModel):
    """Model for daily usage statistics."""

    date: date
    sessions: List[SessionData] = Field(default_factory=list)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens for the day."""
        total = TokenUsage()
        for session in self.sessions:
            session_tokens = session.total_tokens
            total.input += session_tokens.input
            total.output += session_tokens.output
            total.cache_write += session_tokens.cache_write
            total.cache_read += session_tokens.cache_read
        return total

    @computed_field
    @property
    def total_interactions(self) -> int:
        """Calculate total interactions for the day."""
        return sum(session.interaction_count for session in self.sessions)

    @computed_field
    @property
    def models_used(self) -> List[str]:
        """Get unique models used on this day."""
        models = set()
        for session in self.sessions:
            models.update(session.models_used)
        return list(models)

    def calculate_total_cost(self, pricing_data: Dict[str, Any]) -> Decimal:
        """Calculate total cost for the day."""
        return sum(
            (session.calculate_total_cost(pricing_data) for session in self.sessions),
            Decimal("0.0"),
        )


class WeeklyUsage(BaseModel):
    """Model for weekly usage statistics."""

    year: int
    week: int
    start_date: date
    end_date: date
    daily_usage: List[DailyUsage] = Field(default_factory=list)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens for the week."""
        total = TokenUsage()
        for day in self.daily_usage:
            day_tokens = day.total_tokens
            total.input += day_tokens.input
            total.output += day_tokens.output
            total.cache_write += day_tokens.cache_write
            total.cache_read += day_tokens.cache_read
        return total

    @computed_field
    @property
    def total_sessions(self) -> int:
        """Calculate total sessions for the week."""
        return sum(len(day.sessions) for day in self.daily_usage)

    @computed_field
    @property
    def total_interactions(self) -> int:
        """Calculate total interactions for the week."""
        return sum(day.total_interactions for day in self.daily_usage)

    def calculate_total_cost(self, pricing_data: Dict[str, Any]) -> Decimal:
        """Calculate total cost for the week."""
        return sum(
            (day.calculate_total_cost(pricing_data) for day in self.daily_usage),
            Decimal("0.0"),
        )


class MonthlyUsage(BaseModel):
    """Model for monthly usage statistics."""

    year: int
    month: int
    weekly_usage: List[WeeklyUsage] = Field(default_factory=list)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens for the month."""
        total = TokenUsage()
        for week in self.weekly_usage:
            week_tokens = week.total_tokens
            total.input += week_tokens.input
            total.output += week_tokens.output
            total.cache_write += week_tokens.cache_write
            total.cache_read += week_tokens.cache_read
        return total

    @computed_field
    @property
    def total_sessions(self) -> int:
        """Calculate total sessions for the month."""
        return sum(week.total_sessions for week in self.weekly_usage)

    @computed_field
    @property
    def total_interactions(self) -> int:
        """Calculate total interactions for the month."""
        return sum(week.total_interactions for week in self.weekly_usage)

    def calculate_total_cost(self, pricing_data: Dict[str, Any]) -> Decimal:
        """Calculate total cost for the month."""
        return sum(
            (week.calculate_total_cost(pricing_data) for week in self.weekly_usage),
            Decimal("0.0"),
        )


class ModelUsageStats(BaseModel):
    """Model for model-specific usage statistics."""

    model_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))
    first_used: Optional[datetime] = Field(default=None)
    last_used: Optional[datetime] = Field(default=None)


class ModelBreakdownReport(BaseModel):
    """Model for model usage breakdown report."""

    timeframe: str  # "daily", "weekly", "monthly", "all"
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    model_stats: List[ModelUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all models."""
        return sum((model.total_cost for model in self.model_stats), Decimal("0.0"))

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all models."""
        total = TokenUsage()
        for model in self.model_stats:
            total.input += model.total_tokens.input
            total.output += model.total_tokens.output
            total.cache_write += model.total_tokens.cache_write
            total.cache_read += model.total_tokens.cache_read
        return total


class ProjectUsageStats(BaseModel):
    """Model for project-specific usage statistics."""

    project_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))
    models_used: List[str] = Field(default_factory=list)
    first_activity: Optional[datetime] = Field(default=None)
    last_activity: Optional[datetime] = Field(default=None)


class AgentUsageStats(BaseModel):
    """Model for agent-specific usage statistics."""

    agent_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))
    models_used: List[str] = Field(default_factory=list)
    first_used: Optional[datetime] = Field(default=None)
    last_used: Optional[datetime] = Field(default=None)


class AgentBreakdownReport(BaseModel):
    """Model for agent usage breakdown report."""

    timeframe: str
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    agent_stats: List[AgentUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all agents."""
        return sum((agent.total_cost for agent in self.agent_stats), Decimal("0.0"))

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all agents."""
        total = TokenUsage()
        for agent in self.agent_stats:
            total.input += agent.total_tokens.input
            total.output += agent.total_tokens.output
            total.cache_write += agent.total_tokens.cache_write
            total.cache_read += agent.total_tokens.cache_read
        return total


class CategoryUsageStats(BaseModel):
    """Model for delegate_task category usage statistics."""

    category_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))
    models_used: List[str] = Field(default_factory=list)
    first_used: Optional[datetime] = Field(default=None)
    last_used: Optional[datetime] = Field(default=None)


class CategoryBreakdownReport(BaseModel):
    """Model for category usage breakdown report."""

    timeframe: str
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    category_stats: List[CategoryUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all categories."""
        return sum((cat.total_cost for cat in self.category_stats), Decimal("0.0"))

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all categories."""
        total = TokenUsage()
        for cat in self.category_stats:
            total.input += cat.total_tokens.input
            total.output += cat.total_tokens.output
            total.cache_write += cat.total_tokens.cache_write
            total.cache_read += cat.total_tokens.cache_read
        return total


class AgentModelStats(BaseModel):
    """Model for agent × model breakdown statistics."""

    agent_name: str
    model_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))


class CategoryModelStats(BaseModel):
    """Model for category × model breakdown statistics."""

    category_name: str
    model_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))


class CategoryAgentStats(BaseModel):
    """Model for category × agent breakdown statistics."""

    category_name: str
    agent_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))


class SkillUsageStats(BaseModel):
    """Model for skill usage statistics."""

    skill_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))
    models_used: List[str] = Field(default_factory=list)
    agents_used: List[str] = Field(default_factory=list)
    categories_used: List[str] = Field(default_factory=list)
    first_used: Optional[datetime] = Field(default=None)
    last_used: Optional[datetime] = Field(default=None)


class SkillBreakdownReport(BaseModel):
    """Model for skill usage breakdown report."""

    timeframe: str
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    skill_stats: List[SkillUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all skills."""
        return sum((skill.total_cost for skill in self.skill_stats), Decimal("0.0"))

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all skills."""
        total = TokenUsage()
        for skill in self.skill_stats:
            total.input += skill.total_tokens.input
            total.output += skill.total_tokens.output
            total.cache_write += skill.total_tokens.cache_write
            total.cache_read += skill.total_tokens.cache_read
        return total


class ProviderUsageStats(BaseModel):
    """Model for provider/subscription usage statistics."""

    provider_id: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal("0.0"))
    models_used: List[str] = Field(default_factory=list)


class OmoReport(BaseModel):
    """Comprehensive oh-my-opencode usage report."""

    timeframe: str
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)

    # Summary stats
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_cost: Decimal = Field(default=Decimal("0.0"))

    # Breakdowns
    model_stats: List[ModelUsageStats] = Field(default_factory=list)
    agent_stats: List[AgentUsageStats] = Field(default_factory=list)
    category_stats: List[CategoryUsageStats] = Field(default_factory=list)
    agent_model_breakdown: List[AgentModelStats] = Field(default_factory=list)

    # New breakdowns for optimization analytics
    category_model_breakdown: List[CategoryModelStats] = Field(default_factory=list)
    category_agent_breakdown: List[CategoryAgentStats] = Field(default_factory=list)
    skill_stats: List[SkillUsageStats] = Field(default_factory=list)

    # Provider/subscription grouping
    provider_stats: List[ProviderUsageStats] = Field(default_factory=list)
    provider_costs: Dict[str, Decimal] = Field(
        default_factory=dict
    )  # Legacy, kept for backward compatibility


class ProjectBreakdownReport(BaseModel):
    """Model for project usage breakdown report."""

    timeframe: str  # "daily", "weekly", "monthly", "all"
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    project_stats: List[ProjectUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all projects."""
        return sum(project.total_cost for project in self.project_stats)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all projects."""
        total = TokenUsage()
        for project in self.project_stats:
            total.input += project.total_tokens.input
            total.output += project.total_tokens.output
            total.cache_write += project.total_tokens.cache_write
            total.cache_read += project.total_tokens.cache_read
        return total


class TimeframeAnalyzer:
    """Analyzer for different timeframe breakdowns."""

    @staticmethod
    def filter_files_by_time(
        sessions: List[SessionData],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> List[tuple[SessionData, Any]]:
        """Filter files by time range.

        Returns list of (session, file) tuples for files within the time range.
        When start_datetime is provided, it takes precedence and filters by
        file creation time with hour precision.

        Args:
            sessions: List of sessions to filter
            start_date: Start date (inclusive, by session date)
            end_date: End date (inclusive, by session date)
            start_datetime: Start datetime for precise hour filtering (by file time)

        Returns:
            List of (session, file) tuples for matching files
        """
        from .session import InteractionFile

        result: List[tuple[SessionData, InteractionFile]] = []

        for session in sessions:
            for file in session.files:
                # Get file creation time
                file_datetime = None
                if file.time_data and file.time_data.created_datetime:
                    file_datetime = file.time_data.created_datetime

                # If start_datetime provided, filter by precise datetime
                if start_datetime is not None:
                    if file_datetime and file_datetime >= start_datetime:
                        result.append((session, file))
                    continue

                # Otherwise filter by date range (using session date as fallback)
                if start_date or end_date:
                    # Use file datetime if available, otherwise session start_time
                    check_date = None
                    if file_datetime:
                        check_date = file_datetime.date()
                    elif session.start_time:
                        check_date = session.start_time.date()

                    if check_date:
                        if start_date and check_date < start_date:
                            continue
                        if end_date and check_date > end_date:
                            continue

                    result.append((session, file))
                else:
                    # No filtering, include all
                    result.append((session, file))

        return result

    @staticmethod
    def create_daily_breakdown(sessions: List[SessionData]) -> List[DailyUsage]:
        """Create daily breakdown from sessions."""
        daily_data = defaultdict(list)

        for session in sessions:
            if session.start_time:
                session_date = session.start_time.date()
                daily_data[session_date].append(session)

        return [
            DailyUsage(date=date_key, sessions=sessions_list)
            for date_key, sessions_list in sorted(daily_data.items())
        ]

    @staticmethod
    def create_weekly_breakdown(
        daily_usage: List[DailyUsage], week_start_day: int = 0
    ) -> List[WeeklyUsage]:
        """Create weekly breakdown from daily usage.

        Args:
            daily_usage: List of daily usage records
            week_start_day: Day to start week on (0=Monday, 6=Sunday)

        Returns:
            List of WeeklyUsage objects
        """
        from ..utils.time_utils import TimeUtils

        weekly_data = defaultdict(list)

        for day in daily_usage:
            # Get the week start date for this day
            week_start, week_end = TimeUtils.get_custom_week_range(
                day.date, week_start_day
            )

            # Use (week_start, week_end) tuple as key for grouping
            week_key = (week_start, week_end)
            weekly_data[week_key].append(day)

        weekly_breakdown = []
        for (week_start, week_end), days in sorted(weekly_data.items()):
            # For display purposes, calculate ISO week number for the week_start
            year, week, _ = week_start.isocalendar()

            weekly_breakdown.append(
                WeeklyUsage(
                    year=year,
                    week=week,
                    start_date=week_start,
                    end_date=week_end,
                    daily_usage=sorted(days, key=lambda d: d.date),
                )
            )

        return weekly_breakdown

    @staticmethod
    def create_monthly_breakdown(weekly_usage: List[WeeklyUsage]) -> List[MonthlyUsage]:
        """Create monthly breakdown from weekly usage."""
        monthly_data = defaultdict(list)

        for week in weekly_usage:
            # Assign week to month based on start date
            month_key = (week.start_date.year, week.start_date.month)
            monthly_data[month_key].append(week)

        return [
            MonthlyUsage(year=year, month=month, weekly_usage=weeks)
            for (year, month), weeks in sorted(monthly_data.items())
        ]

    @staticmethod
    def create_model_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> ModelBreakdownReport:
        """Create model usage breakdown."""
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        model_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
                "first_used": None,
                "last_used": None,
            }
        )

        for session, file in filtered_files:
            model = file.model_id
            model_stats = model_data[model]

            # Update token counts
            model_stats["tokens"].input += file.tokens.input
            model_stats["tokens"].output += file.tokens.output
            model_stats["tokens"].cache_write += file.tokens.cache_write
            model_stats["tokens"].cache_read += file.tokens.cache_read
            model_stats["interactions"] += 1
            model_stats["cost"] += file.calculate_cost(pricing_data)

            # Track sessions
            model_stats["sessions"].add(session.session_id)

            # Update first/last used times from file timestamp
            file_time = file.time_data.created_datetime if file.time_data else None
            if file_time:
                if (
                    model_stats["first_used"] is None
                    or file_time < model_stats["first_used"]
                ):
                    model_stats["first_used"] = file_time
                if (
                    model_stats["last_used"] is None
                    or file_time > model_stats["last_used"]
                ):
                    model_stats["last_used"] = file_time

        # Convert to ModelUsageStats objects
        model_stats = []
        for model_name, stats in model_data.items():
            model_stats.append(
                ModelUsageStats(
                    model_name=model_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                    first_used=stats["first_used"],
                    last_used=stats["last_used"],
                )
            )

        # Sort by total cost descending
        model_stats.sort(key=lambda x: x.total_cost, reverse=True)

        return ModelBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            model_stats=model_stats,
        )

    @staticmethod
    def create_project_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> "ProjectBreakdownReport":
        """Create project usage breakdown."""
        # Filter sessions by date range if specified
        filtered_sessions = sessions
        if start_date or end_date:
            filtered_sessions = []
            for session in sessions:
                if session.start_time:
                    session_date = session.start_time.date()
                    if start_date and session_date < start_date:
                        continue
                    if end_date and session_date > end_date:
                        continue
                    filtered_sessions.append(session)

        project_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": 0,
                "interactions": 0,
                "cost": Decimal("0.0"),
                "models_used": set(),
                "first_activity": None,
                "last_activity": None,
            }
        )

        for session in filtered_sessions:
            project_name = session.project_name or "Unknown"
            project_stats = project_data[project_name]

            # Update aggregated data
            session_tokens = session.total_tokens
            project_stats["tokens"].input += session_tokens.input
            project_stats["tokens"].output += session_tokens.output
            project_stats["tokens"].cache_write += session_tokens.cache_write
            project_stats["tokens"].cache_read += session_tokens.cache_read

            project_stats["sessions"] += 1
            project_stats["interactions"] += session.interaction_count
            project_stats["cost"] += session.calculate_total_cost(pricing_data)
            project_stats["models_used"].update(session.models_used)

            # Track first/last activity times
            if session.start_time:
                if (
                    project_stats["first_activity"] is None
                    or session.start_time < project_stats["first_activity"]
                ):
                    project_stats["first_activity"] = session.start_time

            if session.end_time:
                if (
                    project_stats["last_activity"] is None
                    or session.end_time > project_stats["last_activity"]
                ):
                    project_stats["last_activity"] = session.end_time

        # Convert to ProjectUsageStats objects
        project_stats = []
        for project_name, stats in project_data.items():
            project_stats.append(
                ProjectUsageStats(
                    project_name=project_name,
                    total_tokens=stats["tokens"],
                    total_sessions=stats["sessions"],
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                    models_used=list(stats["models_used"]),
                    first_activity=stats["first_activity"],
                    last_activity=stats["last_activity"],
                )
            )

        # Sort by total cost descending
        project_stats.sort(key=lambda x: x.total_cost, reverse=True)

        return ProjectBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            project_stats=project_stats,
        )

    @staticmethod
    def create_agent_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> AgentBreakdownReport:
        """Create agent usage breakdown."""
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        agent_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
                "models_used": set(),
                "first_used": None,
                "last_used": None,
            }
        )

        for session, file in filtered_files:
            agent_name = file.agent or "unknown"
            agent_stats = agent_data[agent_name]

            # Update token counts
            agent_stats["tokens"].input += file.tokens.input
            agent_stats["tokens"].output += file.tokens.output
            agent_stats["tokens"].cache_write += file.tokens.cache_write
            agent_stats["tokens"].cache_read += file.tokens.cache_read
            agent_stats["interactions"] += 1
            agent_stats["cost"] += file.calculate_cost(pricing_data)
            agent_stats["models_used"].add(file.model_id)
            agent_stats["sessions"].add(session.session_id)

            # Update first/last used times
            file_time = file.time_data.created_datetime if file.time_data else None
            if file_time:
                if (
                    agent_stats["first_used"] is None
                    or file_time < agent_stats["first_used"]
                ):
                    agent_stats["first_used"] = file_time
                if (
                    agent_stats["last_used"] is None
                    or file_time > agent_stats["last_used"]
                ):
                    agent_stats["last_used"] = file_time

        # Convert to AgentUsageStats objects
        agent_stats_list = []
        for agent_name, stats in agent_data.items():
            agent_stats_list.append(
                AgentUsageStats(
                    agent_name=agent_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                    models_used=list(stats["models_used"]),
                    first_used=stats["first_used"],
                    last_used=stats["last_used"],
                )
            )

        # Sort by interactions descending
        agent_stats_list.sort(key=lambda x: x.total_interactions, reverse=True)

        return AgentBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            agent_stats=agent_stats_list,
        )

    @staticmethod
    def create_category_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> CategoryBreakdownReport:
        """Create delegate_task category usage breakdown."""
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        category_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
                "models_used": set(),
                "first_used": None,
                "last_used": None,
            }
        )

        for session, file in filtered_files:
            # Only count files with a category
            if not file.category:
                continue

            category_name = file.category
            cat_stats = category_data[category_name]

            # Update token counts
            cat_stats["tokens"].input += file.tokens.input
            cat_stats["tokens"].output += file.tokens.output
            cat_stats["tokens"].cache_write += file.tokens.cache_write
            cat_stats["tokens"].cache_read += file.tokens.cache_read
            cat_stats["interactions"] += 1
            cat_stats["cost"] += file.calculate_cost(pricing_data)
            cat_stats["models_used"].add(file.model_id)
            cat_stats["sessions"].add(session.session_id)

            # Update first/last used times
            file_time = file.time_data.created_datetime if file.time_data else None
            if file_time:
                if (
                    cat_stats["first_used"] is None
                    or file_time < cat_stats["first_used"]
                ):
                    cat_stats["first_used"] = file_time
                if cat_stats["last_used"] is None or file_time > cat_stats["last_used"]:
                    cat_stats["last_used"] = file_time

        # Convert to CategoryUsageStats objects
        category_stats_list = []
        for category_name, stats in category_data.items():
            category_stats_list.append(
                CategoryUsageStats(
                    category_name=category_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                    models_used=list(stats["models_used"]),
                    first_used=stats["first_used"],
                    last_used=stats["last_used"],
                )
            )

        # Sort by interactions descending
        category_stats_list.sort(key=lambda x: x.total_interactions, reverse=True)

        return CategoryBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            category_stats=category_stats_list,
        )

    @staticmethod
    def create_skill_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> SkillBreakdownReport:
        """Create skill usage breakdown for oh-my-opencode skills analytics.

        Skills are injected via delegate_task and influence model selection.
        This breakdown helps analyze which skills are most used and their resource
        consumption patterns.
        """
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        skill_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
                "models_used": set(),
                "agents_used": set(),
                "categories_used": set(),
                "first_used": None,
                "last_used": None,
            }
        )

        for session, file in filtered_files:
            # Only count files with skills
            if not file.skills:
                continue

            # Each file may have multiple skills - count each skill separately
            for skill_name in file.skills:
                skill_stats = skill_data[skill_name]

                # Update token counts
                skill_stats["tokens"].input += file.tokens.input
                skill_stats["tokens"].output += file.tokens.output
                skill_stats["tokens"].cache_write += file.tokens.cache_write
                skill_stats["tokens"].cache_read += file.tokens.cache_read
                skill_stats["interactions"] += 1
                skill_stats["cost"] += file.calculate_cost(pricing_data)
                skill_stats["models_used"].add(file.model_id)
                skill_stats["sessions"].add(session.session_id)

                if file.agent:
                    skill_stats["agents_used"].add(file.agent)
                if file.category:
                    skill_stats["categories_used"].add(file.category)

                # Update first/last used times
                file_time = file.time_data.created_datetime if file.time_data else None
                if file_time:
                    if (
                        skill_stats["first_used"] is None
                        or file_time < skill_stats["first_used"]
                    ):
                        skill_stats["first_used"] = file_time
                    if (
                        skill_stats["last_used"] is None
                        or file_time > skill_stats["last_used"]
                    ):
                        skill_stats["last_used"] = file_time

        # Convert to SkillUsageStats objects
        skill_stats_list = []
        for skill_name, stats in skill_data.items():
            skill_stats_list.append(
                SkillUsageStats(
                    skill_name=skill_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                    models_used=list(stats["models_used"]),
                    agents_used=list(stats["agents_used"]),
                    categories_used=list(stats["categories_used"]),
                    first_used=stats["first_used"],
                    last_used=stats["last_used"],
                )
            )

        # Sort by interactions descending
        skill_stats_list.sort(key=lambda x: x.total_interactions, reverse=True)

        return SkillBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            skill_stats=skill_stats_list,
        )

    @staticmethod
    def create_agent_model_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> List[AgentModelStats]:
        """Create agent × model breakdown for detailed analysis."""
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        # Key: (agent, model)
        breakdown_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
            }
        )

        for session, file in filtered_files:
            agent_name = file.agent or "unknown"
            model_name = file.model_id
            key = (agent_name, model_name)
            stats = breakdown_data[key]

            stats["tokens"].input += file.tokens.input
            stats["tokens"].output += file.tokens.output
            stats["tokens"].cache_write += file.tokens.cache_write
            stats["tokens"].cache_read += file.tokens.cache_read
            stats["interactions"] += 1
            stats["cost"] += file.calculate_cost(pricing_data)
            stats["sessions"].add(session.session_id)

        result = []
        for (agent_name, model_name), stats in breakdown_data.items():
            result.append(
                AgentModelStats(
                    agent_name=agent_name,
                    model_name=model_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                )
            )

        # Sort by cost descending
        result.sort(key=lambda x: x.total_cost, reverse=True)
        return result

    @staticmethod
    def create_category_model_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> List[CategoryModelStats]:
        """Create category × model breakdown for subscription optimization.

        This helps analyze which models are used in which categories to optimize
        load distribution across multiple AI subscriptions.
        """
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        # Key: (category, model)
        breakdown_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
            }
        )

        for session, file in filtered_files:
            # Only count files with a category
            if not file.category:
                continue

            category_name = file.category
            model_name = file.model_id
            key = (category_name, model_name)
            stats = breakdown_data[key]

            stats["tokens"].input += file.tokens.input
            stats["tokens"].output += file.tokens.output
            stats["tokens"].cache_write += file.tokens.cache_write
            stats["tokens"].cache_read += file.tokens.cache_read
            stats["interactions"] += 1
            stats["cost"] += file.calculate_cost(pricing_data)
            stats["sessions"].add(session.session_id)

        result = []
        for (category_name, model_name), stats in breakdown_data.items():
            result.append(
                CategoryModelStats(
                    category_name=category_name,
                    model_name=model_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                )
            )

        # Sort by category name, then by interactions descending
        result.sort(key=lambda x: (x.category_name, -x.total_interactions))
        return result

    @staticmethod
    def create_category_agent_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> List[CategoryAgentStats]:
        """Create category × agent breakdown for workload analysis.

        This helps understand which agents work in which categories to
        optimize delegation strategies.
        """
        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        # Key: (category, agent)
        breakdown_data = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
            }
        )

        for session, file in filtered_files:
            # Only count files with a category
            if not file.category:
                continue

            category_name = file.category
            agent_name = file.agent or "unknown"
            key = (category_name, agent_name)
            stats = breakdown_data[key]

            stats["tokens"].input += file.tokens.input
            stats["tokens"].output += file.tokens.output
            stats["tokens"].cache_write += file.tokens.cache_write
            stats["tokens"].cache_read += file.tokens.cache_read
            stats["interactions"] += 1
            stats["cost"] += file.calculate_cost(pricing_data)
            stats["sessions"].add(session.session_id)

        result = []
        for (category_name, agent_name), stats in breakdown_data.items():
            result.append(
                CategoryAgentStats(
                    category_name=category_name,
                    agent_name=agent_name,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                )
            )

        # Sort by category name, then by interactions descending
        result.sort(key=lambda x: (x.category_name, -x.total_interactions))
        return result

    @staticmethod
    def create_omo_report(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        start_datetime: Optional[datetime] = None,
    ) -> OmoReport:
        """Create comprehensive oh-my-opencode usage report.

        Args:
            sessions: List of sessions to analyze
            pricing_data: Model pricing data
            timeframe: Timeframe for analysis
            start_date: Start date filter (YYYY-MM-DD, inclusive)
            end_date: End date filter (YYYY-MM-DD, inclusive)
            start_datetime: Start datetime filter for precise hour filtering
                           (takes precedence over start_date)
        """
        # Get all breakdowns - pass start_datetime for precise filtering
        model_breakdown = TimeframeAnalyzer.create_model_breakdown(
            sessions, pricing_data, timeframe, start_date, end_date, start_datetime
        )
        agent_breakdown = TimeframeAnalyzer.create_agent_breakdown(
            sessions, pricing_data, timeframe, start_date, end_date, start_datetime
        )
        category_breakdown = TimeframeAnalyzer.create_category_breakdown(
            sessions, pricing_data, timeframe, start_date, end_date, start_datetime
        )
        agent_model_breakdown = TimeframeAnalyzer.create_agent_model_breakdown(
            sessions, pricing_data, start_date, end_date, start_datetime
        )

        # New breakdowns for subscription optimization analytics
        category_model_breakdown = TimeframeAnalyzer.create_category_model_breakdown(
            sessions, pricing_data, start_date, end_date, start_datetime
        )
        category_agent_breakdown = TimeframeAnalyzer.create_category_agent_breakdown(
            sessions, pricing_data, start_date, end_date, start_datetime
        )
        skill_breakdown = TimeframeAnalyzer.create_skill_breakdown(
            sessions, pricing_data, timeframe, start_date, end_date, start_datetime
        )

        # Calculate provider stats directly from filtered files
        provider_data: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "tokens": TokenUsage(),
                "sessions": set(),
                "interactions": 0,
                "cost": Decimal("0.0"),
                "models_used": set(),
            }
        )

        # Use file-level filtering for precise time ranges
        filtered_files = TimeframeAnalyzer.filter_files_by_time(
            sessions, start_date, end_date, start_datetime
        )

        for session, file in filtered_files:
            provider = file.provider_id or "unknown"
            stats = provider_data[provider]
            stats["tokens"].input += file.tokens.input
            stats["tokens"].output += file.tokens.output
            stats["tokens"].cache_write += file.tokens.cache_write
            stats["tokens"].cache_read += file.tokens.cache_read
            stats["interactions"] += 1
            stats["cost"] += file.calculate_cost(pricing_data)
            stats["sessions"].add(session.session_id)
            stats["models_used"].add(file.model_id)

        # Convert to ProviderUsageStats list
        provider_stats_list = []
        for provider_id, stats in provider_data.items():
            provider_stats_list.append(
                ProviderUsageStats(
                    provider_id=provider_id,
                    total_tokens=stats["tokens"],
                    total_sessions=len(stats["sessions"]),
                    total_interactions=stats["interactions"],
                    total_cost=stats["cost"],
                    models_used=list(stats["models_used"]),
                )
            )
        # Sort by interactions descending
        provider_stats_list.sort(key=lambda x: x.total_interactions, reverse=True)

        # Legacy provider_costs for backward compatibility
        provider_costs: Dict[str, Decimal] = {
            provider: stats["cost"] for provider, stats in provider_data.items()
        }

        # Calculate totals from filtered files
        total_sessions = len(set(session.session_id for session, _ in filtered_files))

        return OmoReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            total_sessions=total_sessions,
            total_interactions=sum(
                m.total_interactions for m in model_breakdown.model_stats
            ),
            total_tokens=model_breakdown.total_tokens,
            total_cost=model_breakdown.total_cost,
            model_stats=model_breakdown.model_stats,
            agent_stats=agent_breakdown.agent_stats,
            category_stats=category_breakdown.category_stats,
            agent_model_breakdown=agent_model_breakdown,
            category_model_breakdown=category_model_breakdown,
            category_agent_breakdown=category_agent_breakdown,
            skill_stats=skill_breakdown.skill_stats,
            provider_stats=provider_stats_list,
            provider_costs=dict(provider_costs),
        )
