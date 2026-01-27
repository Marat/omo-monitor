"""Report generation service for OpenCode Monitor."""

from typing import List, Dict, Any, Optional
from datetime import date, datetime
from decimal import Decimal
from collections import defaultdict
from rich.console import Console
from rich.panel import Panel

from ..models.session import SessionData
from ..models.analytics import (
    DailyUsage,
    WeeklyUsage,
    MonthlyUsage,
    ModelBreakdownReport,
    ProjectBreakdownReport,
    AgentBreakdownReport,
    CategoryBreakdownReport,
    SkillBreakdownReport,
    AgentModelStats,
    OmoReport,
)
from ..models.limits import LimitsConfig, LimitsReport
from ..ui.tables import TableFormatter
from ..services.session_analyzer import SessionAnalyzer
from ..services.limits_analyzer import LimitsAnalyzer
from ..config import ModelPricing


class ReportGenerator:
    """Service for generating various types of reports."""

    def __init__(self, analyzer: SessionAnalyzer, console: Optional[Console] = None):
        """Initialize report generator.

        Args:
            analyzer: SessionAnalyzer instance
            console: Rich console for output
        """
        self.analyzer = analyzer
        self.table_formatter = TableFormatter(console)
        self.console = console or Console()

    def _get_model_breakdown_for_sessions(
        self, sessions: List[SessionData]
    ) -> List[Dict[str, Any]]:
        """Calculate per-model breakdown for a set of sessions.

        Args:
            sessions: List of sessions to analyze

        Returns:
            List of model breakdown dicts sorted by cost descending
        """
        model_data: Dict[str, Dict[str, Any]] = {}

        for session in sessions:
            for file in session.files:
                model = file.model_id
                if model not in model_data:
                    model_data[model] = {
                        "sessions": set(),
                        "interactions": 0,
                        "tokens": 0,
                        "cost": Decimal("0.0"),
                    }
                model_data[model]["sessions"].add(session.session_id)
                model_data[model]["interactions"] += 1
                model_data[model]["tokens"] += file.tokens.total
                model_data[model]["cost"] += file.calculate_cost(
                    self.analyzer.pricing_data
                )

        results = []
        for model, data in model_data.items():
            results.append(
                {
                    "model": model,
                    "sessions": len(data["sessions"]),
                    "interactions": data["interactions"],
                    "tokens": data["tokens"],
                    "cost": data["cost"],
                }
            )

        return sorted(results, key=lambda x: x["cost"], reverse=True)

    def generate_single_session_report(
        self, session_path: str, output_format: str = "table"
    ) -> Optional[Dict[str, Any]]:
        """Generate report for a single session.

        Args:
            session_path: Path to session directory
            output_format: Output format ("table", "json", "csv")

        Returns:
            Report data or None if session not found
        """
        session = self.analyzer.analyze_single_session(session_path)
        if not session:
            return None

        # Get detailed statistics
        stats = self.analyzer.get_session_statistics(session)
        health = self.analyzer.validate_session_health(session)

        report_data = {
            "type": "single_session",
            "session": session,
            "statistics": stats,
            "health": health,
        }

        if output_format == "table":
            self._display_single_session_table(session, stats, health)
        elif output_format == "json":
            return self._format_single_session_json(session, stats, health)
        elif output_format == "csv":
            return self._format_single_session_csv(session, stats)

        return report_data

    def generate_sessions_summary_report(
        self, base_path: str, limit: Optional[int] = None, output_format: str = "table"
    ) -> Dict[str, Any]:
        """Generate summary report for all sessions.

        Args:
            base_path: Path to directory containing sessions
            limit: Maximum number of sessions to analyze
            output_format: Output format ("table", "json", "csv")

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path, limit)
        summary = self.analyzer.get_sessions_summary(sessions)

        report_data = {
            "type": "sessions_summary",
            "sessions": sessions,
            "summary": summary,
        }

        if output_format == "table":
            self._display_sessions_summary_table(sessions, summary)
        elif output_format == "json":
            return self._format_sessions_summary_json(sessions, summary)
        elif output_format == "csv":
            return self._format_sessions_summary_csv(sessions)

        return report_data

    def generate_daily_report(
        self,
        base_path: str,
        month: Optional[str] = None,
        output_format: str = "table",
        breakdown: bool = False,
    ) -> Dict[str, Any]:
        """Generate daily breakdown report.

        Args:
            base_path: Path to directory containing sessions
            month: Optional month filter (YYYY-MM format)
            output_format: Output format ("table", "json", "csv")

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply month filter if specified
        if month:
            from ..utils.time_utils import TimeUtils

            month_data = TimeUtils.parse_month_string(month)
            if month_data:
                year, month_num = month_data
                start_date, end_date = TimeUtils.get_month_range(year, month_num)
                sessions = self.analyzer.filter_sessions_by_date(
                    sessions, start_date, end_date
                )

        daily_usage = self.analyzer.create_daily_breakdown(sessions)

        report_data = {
            "type": "daily_breakdown",
            "daily_usage": daily_usage,
            "filter": {"month": month} if month else None,
        }

        if output_format == "table":
            self._display_daily_breakdown_table(daily_usage, breakdown)
        elif output_format == "json":
            return self._format_daily_breakdown_json(daily_usage)
        elif output_format == "csv":
            return self._format_daily_breakdown_csv(daily_usage)

        return report_data

    def generate_weekly_report(
        self,
        base_path: str,
        year: Optional[int] = None,
        output_format: str = "table",
        breakdown: bool = False,
        week_start_day: int = 0,
    ) -> Dict[str, Any]:
        """Generate weekly breakdown report.

        Args:
            base_path: Path to directory containing sessions
            year: Optional year filter
            output_format: Output format ("table", "json", "csv")
            breakdown: Show per-model breakdown
            week_start_day: Day to start week on (0=Monday, 6=Sunday)

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply year filter if specified
        if year:
            from ..utils.time_utils import TimeUtils

            start_date, end_date = TimeUtils.get_year_range(year)
            sessions = self.analyzer.filter_sessions_by_date(
                sessions, start_date, end_date
            )

        weekly_usage = self.analyzer.create_weekly_breakdown(sessions, week_start_day)

        report_data = {
            "type": "weekly_breakdown",
            "weekly_usage": weekly_usage,
            "filter": {"year": year, "week_start_day": week_start_day}
            if year or week_start_day != 0
            else None,
        }

        if output_format == "table":
            self._display_weekly_breakdown_table(
                weekly_usage, breakdown, week_start_day
            )
        elif output_format == "json":
            return self._format_weekly_breakdown_json(weekly_usage)
        elif output_format == "csv":
            return self._format_weekly_breakdown_csv(weekly_usage)

        return report_data

    def generate_monthly_report(
        self,
        base_path: str,
        year: Optional[int] = None,
        output_format: str = "table",
        breakdown: bool = False,
    ) -> Dict[str, Any]:
        """Generate monthly breakdown report.

        Args:
            base_path: Path to directory containing sessions
            year: Optional year filter
            output_format: Output format ("table", "json", "csv")

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply year filter if specified
        if year:
            from ..utils.time_utils import TimeUtils

            start_date, end_date = TimeUtils.get_year_range(year)
            sessions = self.analyzer.filter_sessions_by_date(
                sessions, start_date, end_date
            )

        monthly_usage = self.analyzer.create_monthly_breakdown(sessions)

        report_data = {
            "type": "monthly_breakdown",
            "monthly_usage": monthly_usage,
            "filter": {"year": year} if year else None,
        }

        if output_format == "table":
            self._display_monthly_breakdown_table(monthly_usage, breakdown)
        elif output_format == "json":
            return self._format_monthly_breakdown_json(monthly_usage)
        elif output_format == "csv":
            return self._format_monthly_breakdown_csv(monthly_usage)

        return report_data

    def generate_models_report(
        self,
        base_path: str,
        timeframe: str = "all",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "table",
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate model usage breakdown report.

        Args:
            base_path: Path to directory containing sessions
            timeframe: Timeframe for analysis
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            output_format: Output format ("table", "json", "csv")
            project: Filter by project name (partial match)

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply project filter if specified
        if project:
            sessions = self.analyzer.filter_sessions_by_project(sessions, project)

        # Parse date filters
        from ..utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        model_breakdown = self.analyzer.create_model_breakdown(
            sessions, timeframe, parsed_start_date, parsed_end_date
        )

        report_data = {
            "type": "models_breakdown",
            "model_breakdown": model_breakdown,
            "filter": {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "project": project,
            },
        }

        if output_format == "table":
            self._display_models_breakdown_table(model_breakdown)
        elif output_format == "json":
            return self._format_models_breakdown_json(model_breakdown)
        elif output_format == "csv":
            return self._format_models_breakdown_csv(model_breakdown)

        return report_data

    def generate_projects_report(
        self,
        base_path: str,
        timeframe: str = "all",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "table",
    ) -> Dict[str, Any]:
        """Generate project usage breakdown report.

        Args:
            base_path: Path to directory containing sessions
            timeframe: Timeframe for analysis
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            output_format: Output format ("table", "json", "csv")

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Parse date filters
        from ..utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        project_breakdown = self.analyzer.create_project_breakdown(
            sessions, timeframe, parsed_start_date, parsed_end_date
        )

        report_data = {
            "type": "projects_breakdown",
            "project_breakdown": project_breakdown,
            "filter": {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
            },
        }

        if output_format == "table":
            self._display_projects_breakdown_table(project_breakdown)
        elif output_format == "json":
            return self._format_projects_breakdown_json(project_breakdown)
        elif output_format == "csv":
            return self._format_projects_breakdown_csv(project_breakdown)

        return report_data

    def generate_agents_report(
        self,
        base_path: str,
        timeframe: str = "all",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "table",
        breakdown: bool = False,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate agent usage breakdown report (oh-my-opencode agents).

        Args:
            base_path: Path to directory containing sessions
            timeframe: Timeframe for analysis
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            output_format: Output format ("table", "json", "csv")
            breakdown: Show detailed agent × model breakdown
            project: Filter by project name (partial match)

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply project filter if specified
        if project:
            sessions = self.analyzer.filter_sessions_by_project(sessions, project)

        # Parse date filters
        from ..utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        agent_breakdown = self.analyzer.create_agent_breakdown(
            sessions, timeframe, parsed_start_date, parsed_end_date
        )

        # Get agent × model breakdown if requested
        agent_model_breakdown = None
        if breakdown:
            agent_model_breakdown = self.analyzer.create_agent_model_breakdown(
                sessions, parsed_start_date, parsed_end_date
            )

        report_data = {
            "type": "agents_breakdown",
            "agent_breakdown": agent_breakdown,
            "agent_model_breakdown": agent_model_breakdown,
            "filter": {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "project": project,
            },
        }

        if output_format == "table":
            self._display_agents_breakdown_table(agent_breakdown, agent_model_breakdown)
        elif output_format == "json":
            return self._format_agents_breakdown_json(
                agent_breakdown, agent_model_breakdown
            )
        elif output_format == "csv":
            return self._format_agents_breakdown_csv(
                agent_breakdown, agent_model_breakdown
            )

        return report_data

    def generate_categories_report(
        self,
        base_path: str,
        timeframe: str = "all",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "table",
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate delegate_task category usage breakdown report.

        Args:
            base_path: Path to directory containing sessions
            timeframe: Timeframe for analysis
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            output_format: Output format ("table", "json", "csv")
            project: Filter by project name (partial match)

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply project filter if specified
        if project:
            sessions = self.analyzer.filter_sessions_by_project(sessions, project)

        # Parse date filters
        from ..utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        category_breakdown = self.analyzer.create_category_breakdown(
            sessions, timeframe, parsed_start_date, parsed_end_date
        )

        report_data = {
            "type": "categories_breakdown",
            "category_breakdown": category_breakdown,
            "filter": {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "project": project,
            },
        }

        if output_format == "table":
            self._display_categories_breakdown_table(category_breakdown)
        elif output_format == "json":
            return self._format_categories_breakdown_json(category_breakdown)
        elif output_format == "csv":
            return self._format_categories_breakdown_csv(category_breakdown)

        return report_data

    def generate_skills_report(
        self,
        base_path: str,
        timeframe: str = "all",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "table",
        project: Optional[str] = None,
        start_datetime: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Generate skill usage breakdown report (oh-my-opencode skills).

        Args:
            base_path: Path to directory containing sessions
            timeframe: Timeframe for analysis
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            output_format: Output format ("table", "json", "csv")
            project: Filter by project name (partial match)
            start_datetime: Start datetime for precise hour filtering (overrides start_date)

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply project filter if specified
        if project:
            sessions = self.analyzer.filter_sessions_by_project(sessions, project)

        # Parse date filters
        from ..utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        skill_breakdown = self.analyzer.create_skill_breakdown(
            sessions, timeframe, parsed_start_date, parsed_end_date, start_datetime
        )

        report_data = {
            "type": "skills_breakdown",
            "skill_breakdown": skill_breakdown,
            "filter": {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "project": project,
            },
        }

        if output_format == "table":
            self._display_skills_breakdown_table(skill_breakdown)
        elif output_format == "json":
            return self._format_skills_breakdown_json(skill_breakdown)
        elif output_format == "csv":
            return self._format_skills_breakdown_csv(skill_breakdown)

        return report_data

    def generate_omo_report(
        self,
        base_path: str,
        timeframe: str = "all",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "table",
        start_datetime: Optional[datetime] = None,
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate comprehensive oh-my-opencode usage report.

        Shows all statistics in one place: models, agents, categories, and provider costs.

        Args:
            base_path: Path to directory containing sessions
            timeframe: Timeframe for analysis
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            output_format: Output format ("table", "json", "csv")
            start_datetime: Start datetime for precise hour filtering (overrides start_date)
            project: Filter by project name (partial match)

        Returns:
            Report data
        """
        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply project filter if specified
        if project:
            sessions = self.analyzer.filter_sessions_by_project(sessions, project)

        # Parse date filters
        from ..utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        omo_report = self.analyzer.create_omo_report(
            sessions, timeframe, parsed_start_date, parsed_end_date, start_datetime
        )

        report_data = {
            "type": "omo_report",
            "omo_report": omo_report,
            "filter": {
                "timeframe": timeframe,
                "start_date": start_date,
                "end_date": end_date,
                "project": project,
            },
        }

        if output_format == "table":
            self._display_omo_report_table(omo_report)
        elif output_format == "json":
            return self._format_omo_report_json(omo_report)
        elif output_format == "csv":
            return self._format_omo_report_csv(omo_report)

        return report_data

    # Table display methods
    def _display_single_session_table(
        self, session: SessionData, stats: Dict[str, Any], health: Dict[str, Any]
    ):
        """Display single session report as table."""
        # Create session details table
        table = self.table_formatter.create_session_table(
            session, self.analyzer.pricing_data
        )
        self.console.print(table)

        # Create summary panel
        summary_panel = self.table_formatter.create_summary_panel(
            [session], self.analyzer.pricing_data
        )
        self.console.print(summary_panel)

        # Show health warnings if any
        if health["warnings"]:
            warning_text = "\n".join(
                [f"⚠️  {warning}" for warning in health["warnings"]]
            )
            warning_panel = Panel(warning_text, title="Warnings", border_style="yellow")
            self.console.print(warning_panel)

    def _display_sessions_summary_table(
        self, sessions: List[SessionData], summary: Dict[str, Any]
    ):
        """Display sessions summary as table."""
        table = self.table_formatter.create_sessions_table(
            sessions, self.analyzer.pricing_data
        )
        self.console.print(table)

        summary_panel = self.table_formatter.create_summary_panel(
            sessions, self.analyzer.pricing_data
        )
        self.console.print(summary_panel)

    def _display_daily_breakdown_table(
        self, daily_usage: List[DailyUsage], breakdown: bool = False
    ):
        """Display daily breakdown as table."""
        if breakdown:
            from rich.table import Table

            table = Table(
                title="Daily Usage Breakdown",
                show_header=True,
                header_style="bold blue",
                title_style="bold magenta",
            )

            table.add_column("Date / Model", style="cyan", no_wrap=True)
            table.add_column("Sessions", justify="right", style="green")
            table.add_column("Interactions", justify="right", style="yellow")
            table.add_column("Total Tokens", justify="right", style="white")
            table.add_column("Cost", justify="right", style="red")

            for day in daily_usage:
                day_cost = day.calculate_total_cost(self.analyzer.pricing_data)
                table.add_row(
                    day.date.strftime("%Y-%m-%d"),
                    f"{len(day.sessions)}",
                    f"{day.total_interactions}",
                    f"{day.total_tokens.total:,}",
                    f"${day_cost:.2f}",
                )

                model_breakdown = self._get_model_breakdown_for_sessions(day.sessions)
                for model_data in model_breakdown:
                    table.add_row(
                        f"  ↳ {model_data['model']}",
                        f"{model_data['sessions']}",
                        f"{model_data['interactions']}",
                        f"{model_data['tokens']:,}",
                        f"${model_data['cost']:.2f}",
                        style="dim",
                    )

            self.console.print(table)
        else:
            table = self.table_formatter.create_daily_table(
                daily_usage, self.analyzer.pricing_data
            )
            self.console.print(table)

    def _display_weekly_breakdown_table(
        self,
        weekly_usage: List[WeeklyUsage],
        breakdown: bool = False,
        week_start_day: int = 0,
    ):
        """Display weekly breakdown as table.

        Args:
            weekly_usage: List of weekly usage data
            breakdown: Show per-model breakdown
            week_start_day: Day week starts on (0=Monday, 6=Sunday)
        """
        from rich.table import Table
        from ..utils.time_utils import TimeUtils, WEEKDAY_NAMES

        title = "Weekly Usage Breakdown"
        if week_start_day != 0:
            day_name = WEEKDAY_NAMES[week_start_day]
            title += f" (weeks start on {day_name})"

        table = Table(
            title=title,
            show_header=True,
            header_style="bold blue",
            title_style="bold magenta",
        )

        table.add_column("Week", style="cyan", no_wrap=True)
        table.add_column("Date Range", style="dim cyan", no_wrap=False)
        table.add_column("Sessions", justify="right", style="green")
        table.add_column("Interactions", justify="right", style="yellow")
        table.add_column("Total Tokens", justify="right", style="white")
        table.add_column("Cost", justify="right", style="red")

        for week in weekly_usage:
            week_cost = week.calculate_total_cost(self.analyzer.pricing_data)
            week_label = f"{week.year}-W{week.week:02d}"
            date_range = TimeUtils.format_week_range(week.start_date, week.end_date)

            table.add_row(
                week_label,
                date_range,
                f"{week.total_sessions}",
                f"{week.total_interactions}",
                f"{week.total_tokens.total:,}",
                f"${week_cost:.2f}",
            )

            if breakdown:
                week_sessions = []
                for day in week.daily_usage:
                    week_sessions.extend(day.sessions)

                model_breakdown = self._get_model_breakdown_for_sessions(week_sessions)
                for model_data in model_breakdown:
                    table.add_row(
                        "",
                        f"  ↳ {model_data['model']}",
                        f"{model_data['sessions']}",
                        f"{model_data['interactions']}",
                        f"{model_data['tokens']:,}",
                        f"${model_data['cost']:.2f}",
                        style="dim",
                    )

        self.console.print(table)

    def _display_monthly_breakdown_table(
        self, monthly_usage: List[MonthlyUsage], breakdown: bool = False
    ):
        """Display monthly breakdown as table."""
        from rich.table import Table

        table = Table(
            title="Monthly Usage Breakdown",
            show_header=True,
            header_style="bold blue",
            title_style="bold magenta",
        )

        table.add_column("Month / Model", style="cyan", no_wrap=True)
        table.add_column("Sessions", justify="right", style="green")
        table.add_column("Interactions", justify="right", style="yellow")
        table.add_column("Total Tokens", justify="right", style="white")
        table.add_column("Cost", justify="right", style="red")

        for month in monthly_usage:
            month_cost = month.calculate_total_cost(self.analyzer.pricing_data)
            table.add_row(
                f"{month.year}-{month.month:02d}",
                f"{month.total_sessions}",
                f"{month.total_interactions}",
                f"{month.total_tokens.total:,}",
                f"${month_cost:.2f}",
            )

            if breakdown:
                month_sessions = []
                for week in month.weekly_usage:
                    for day in week.daily_usage:
                        month_sessions.extend(day.sessions)

                model_breakdown = self._get_model_breakdown_for_sessions(month_sessions)
                for model_data in model_breakdown:
                    table.add_row(
                        f"  ↳ {model_data['model']}",
                        f"{model_data['sessions']}",
                        f"{model_data['interactions']}",
                        f"{model_data['tokens']:,}",
                        f"${model_data['cost']:.2f}",
                        style="dim",
                    )

        self.console.print(table)

    def _display_models_breakdown_table(self, model_breakdown: ModelBreakdownReport):
        """Display models breakdown as table."""
        table = self.table_formatter.create_model_breakdown_table(
            model_breakdown.model_stats
        )
        self.console.print(table)

    def _display_projects_breakdown_table(
        self, project_breakdown: ProjectBreakdownReport
    ):
        """Display projects breakdown as table."""
        from rich.table import Table

        table = Table(title="Project Usage Breakdown", show_header=True)

        table.add_column("Project", style="cyan")
        table.add_column("Sessions", justify="right", style="green")
        table.add_column("Interactions", justify="right", style="green")
        table.add_column("Total Tokens", justify="right", style="bold blue")
        table.add_column("Cost", justify="right", style="red")
        table.add_column("Models Used", style="dim cyan")

        for project in project_breakdown.project_stats:
            # Truncate models list if too long
            models_display = ", ".join(project.models_used)
            if len(models_display) > 40:
                models_display = models_display[:37] + "..."

            table.add_row(
                project.project_name,
                f"{project.total_sessions}",
                f"{project.total_interactions}",
                f"{project.total_tokens.total:,}",
                f"${project.total_cost:.4f}",
                models_display,
            )

        self.console.print(table)

        # Add summary
        from rich.panel import Panel

        summary_text = (
            f"Total: {len(project_breakdown.project_stats)} projects, "
            f"{sum(p.total_sessions for p in project_breakdown.project_stats)} sessions, "
            f"{sum(p.total_interactions for p in project_breakdown.project_stats)} interactions, "
            f"{project_breakdown.total_tokens.total:,} tokens, "
            f"${project_breakdown.total_cost:.2f}"
        )
        summary_panel = Panel(summary_text, title="Summary", border_style="green")
        self.console.print(summary_panel)

    def _display_agents_breakdown_table(
        self,
        agent_breakdown: AgentBreakdownReport,
        agent_model_breakdown: Optional[List[AgentModelStats]] = None,
    ):
        """Display agents breakdown as table."""
        from rich.table import Table

        if agent_model_breakdown:
            # Show detailed agent × model breakdown
            table = Table(
                title="Agent × Model Breakdown (oh-my-opencode)", show_header=True
            )

            table.add_column("Agent", style="cyan")
            table.add_column("Model", style="magenta")
            table.add_column("Sessions", justify="right", style="green")
            table.add_column("Interactions", justify="right", style="green")
            table.add_column("Total Tokens", justify="right", style="bold blue")
            table.add_column("Cost", justify="right", style="red")

            for item in agent_model_breakdown:
                table.add_row(
                    item.agent_name or "(no agent)",
                    item.model_name,
                    f"{item.total_sessions}",
                    f"{item.total_interactions}",
                    f"{item.total_tokens.total:,}",
                    f"${item.total_cost:.4f}",
                )

            self.console.print(table)

            # Summary for breakdown
            total_cost = sum(item.total_cost for item in agent_model_breakdown)
            total_interactions = sum(
                item.total_interactions for item in agent_model_breakdown
            )
            summary_text = (
                f"Total: {len(agent_model_breakdown)} agent×model combinations, "
                f"{total_interactions} interactions, "
                f"${total_cost:.2f}"
            )
        else:
            # Standard agent breakdown
            table = Table(
                title="Agent Usage Breakdown (oh-my-opencode)", show_header=True
            )

            table.add_column("Agent", style="cyan")
            table.add_column("Sessions", justify="right", style="green")
            table.add_column("Interactions", justify="right", style="green")
            table.add_column("Total Tokens", justify="right", style="bold blue")
            table.add_column("Cost", justify="right", style="red")
            table.add_column("Models Used", style="dim cyan")

            for agent in agent_breakdown.agent_stats:
                models_display = ", ".join(agent.models_used)
                if len(models_display) > 40:
                    models_display = models_display[:37] + "..."

                table.add_row(
                    agent.agent_name or "(no agent)",
                    f"{agent.total_sessions}",
                    f"{agent.total_interactions}",
                    f"{agent.total_tokens.total:,}",
                    f"${agent.total_cost:.4f}",
                    models_display,
                )

            self.console.print(table)

            summary_text = (
                f"Total: {len(agent_breakdown.agent_stats)} agents, "
                f"{sum(a.total_sessions for a in agent_breakdown.agent_stats)} sessions, "
                f"{sum(a.total_interactions for a in agent_breakdown.agent_stats)} interactions, "
                f"{agent_breakdown.total_tokens.total:,} tokens, "
                f"${agent_breakdown.total_cost:.2f}"
            )

        summary_panel = Panel(summary_text, title="Summary", border_style="green")
        self.console.print(summary_panel)

    def _display_categories_breakdown_table(
        self, category_breakdown: CategoryBreakdownReport
    ):
        """Display categories breakdown as table."""
        from rich.table import Table

        table = Table(
            title="Category Usage Breakdown (delegate_task)", show_header=True
        )

        table.add_column("Category", style="cyan")
        table.add_column("Sessions", justify="right", style="green")
        table.add_column("Interactions", justify="right", style="green")
        table.add_column("Total Tokens", justify="right", style="bold blue")
        table.add_column("Cost", justify="right", style="red")
        table.add_column("Models Used", style="dim cyan")

        for category in category_breakdown.category_stats:
            models_display = ", ".join(category.models_used)
            if len(models_display) > 40:
                models_display = models_display[:37] + "..."

            table.add_row(
                category.category_name or "(no category)",
                f"{category.total_sessions}",
                f"{category.total_interactions}",
                f"{category.total_tokens.total:,}",
                f"${category.total_cost:.4f}",
                models_display,
            )

        self.console.print(table)

        # Add summary
        summary_text = (
            f"Total: {len(category_breakdown.category_stats)} categories, "
            f"{sum(c.total_sessions for c in category_breakdown.category_stats)} sessions, "
            f"{sum(c.total_interactions for c in category_breakdown.category_stats)} interactions, "
            f"{category_breakdown.total_tokens.total:,} tokens, "
            f"${category_breakdown.total_cost:.2f}"
        )
        summary_panel = Panel(summary_text, title="Summary", border_style="green")
        self.console.print(summary_panel)

    def _display_skills_breakdown_table(self, skill_breakdown: SkillBreakdownReport):
        """Display skills breakdown as table."""
        from rich.table import Table

        if not skill_breakdown.skill_stats:
            self.console.print(
                "[dim]No skills data found. Skills are logged when using "
                "delegate_task with skills parameter in oh-my-opencode.[/dim]"
            )
            return

        table = Table(title="Skill Usage Breakdown (oh-my-opencode)", show_header=True)

        table.add_column("Skill", style="cyan")
        table.add_column("Sessions", justify="right", style="green")
        table.add_column("Interactions", justify="right", style="green")
        table.add_column("Total Tokens", justify="right", style="bold blue")
        table.add_column("Tok/Req", justify="right", style="dim")
        table.add_column("Agents", style="dim cyan")
        table.add_column("Categories", style="dim magenta")

        for skill in skill_breakdown.skill_stats:
            avg_tokens = (
                skill.total_tokens.total // skill.total_interactions
                if skill.total_interactions > 0
                else 0
            )
            agents_display = ", ".join(skill.agents_used[:3])
            if len(skill.agents_used) > 3:
                agents_display += f" (+{len(skill.agents_used) - 3})"
            cats_display = ", ".join(skill.categories_used[:3])
            if len(skill.categories_used) > 3:
                cats_display += f" (+{len(skill.categories_used) - 3})"

            table.add_row(
                skill.skill_name,
                f"{skill.total_sessions}",
                f"{skill.total_interactions}",
                f"{skill.total_tokens.total:,}",
                f"{avg_tokens:,}",
                agents_display,
                cats_display,
            )

        self.console.print(table)

        # Add summary
        summary_text = (
            f"Total: {len(skill_breakdown.skill_stats)} skills, "
            f"{sum(s.total_sessions for s in skill_breakdown.skill_stats)} sessions, "
            f"{sum(s.total_interactions for s in skill_breakdown.skill_stats)} interactions, "
            f"{skill_breakdown.total_tokens.total:,} tokens"
        )
        summary_panel = Panel(summary_text, title="Summary", border_style="green")
        self.console.print(summary_panel)

    def _display_omo_report_table(self, omo_report: OmoReport):
        """Display comprehensive oh-my-opencode report as tables."""
        from rich.table import Table
        from rich.rule import Rule
        from collections import defaultdict

        # Header with period info
        period_str = "All time"
        if omo_report.start_date and omo_report.end_date:
            if omo_report.start_date == omo_report.end_date:
                period_str = f"{omo_report.start_date}"
            else:
                period_str = f"{omo_report.start_date} - {omo_report.end_date}"
        elif omo_report.start_date:
            period_str = f"From {omo_report.start_date}"
        elif omo_report.end_date:
            period_str = f"Until {omo_report.end_date}"

        self.console.print(
            Rule(f"[bold magenta]oh-my-opencode Report: {period_str}[/bold magenta]")
        )
        self.console.print()

        # Summary table instead of panel
        tokens = omo_report.total_tokens
        summary_table = Table(show_header=False, box=None, padding=(0, 2))
        summary_table.add_column("Label", style="bold")
        summary_table.add_column("Value", style="cyan")
        summary_table.add_row("Sessions", f"{omo_report.total_sessions}")
        summary_table.add_row("Requests", f"{omo_report.total_interactions}")
        summary_table.add_row(
            "[bold]Total tokens[/bold]", f"[bold cyan]{tokens.total:,}[/bold cyan]"
        )
        self.console.print(Panel(summary_table, title="Summary", border_style="green"))
        self.console.print()

        # Provider usage table
        if omo_report.provider_stats:
            self.console.print(Rule("[bold cyan]By Provider[/bold cyan]"))
            provider_table = Table(show_header=True, header_style="bold blue")
            provider_table.add_column("Provider", style="cyan")
            provider_table.add_column("Req", justify="right", style="green")
            provider_table.add_column("Total Tokens", justify="right", style="yellow")
            provider_table.add_column("Tok/Req", justify="right", style="dim")
            provider_table.add_column("Models", style="dim")

            for provider in omo_report.provider_stats:
                avg_tokens = (
                    provider.total_tokens.total // provider.total_interactions
                    if provider.total_interactions > 0
                    else 0
                )
                models_str = ", ".join(sorted(provider.models_used)[:3])
                if len(provider.models_used) > 3:
                    models_str += f" (+{len(provider.models_used) - 3})"

                provider_table.add_row(
                    provider.provider_id,
                    f"{provider.total_interactions}",
                    f"{provider.total_tokens.total:,}",
                    f"{avg_tokens:,}",
                    models_str,
                )

            self.console.print(provider_table)
            self.console.print()

        # Model -> Agents table (reverse hierarchy)
        if omo_report.agent_model_breakdown:
            self.console.print(Rule("[bold cyan]Model -> Agents/Tools[/bold cyan]"))

            # Group by model
            model_agents = defaultdict(list)
            for item in omo_report.agent_model_breakdown:
                model_agents[item.model_name].append(item)

            model_table = Table(show_header=True, header_style="bold blue")
            model_table.add_column("Model / Agent", style="cyan")
            model_table.add_column("Req", justify="right", style="green")
            model_table.add_column("Total Tokens", justify="right", style="yellow")
            model_table.add_column("Tok/Req", justify="right", style="dim")

            # Sort models by total requests
            model_totals = {}
            for model, items in model_agents.items():
                model_totals[model] = sum(i.total_interactions for i in items)

            for model in sorted(
                model_totals.keys(), key=lambda m: model_totals[m], reverse=True
            ):
                items = model_agents[model]
                total_req = sum(i.total_interactions for i in items)
                total_tokens = sum(i.total_tokens.total for i in items)
                avg_tokens = total_tokens // total_req if total_req > 0 else 0

                model_table.add_row(
                    f"[bold]{model}[/bold]",
                    f"[bold]{total_req}[/bold]",
                    f"[bold]{total_tokens:,}[/bold]",
                    f"[bold]{avg_tokens:,}[/bold]",
                )

                # Agent rows (indented)
                for item in sorted(
                    items, key=lambda x: x.total_interactions, reverse=True
                ):
                    item_avg = (
                        item.total_tokens.total // item.total_interactions
                        if item.total_interactions > 0
                        else 0
                    )
                    model_table.add_row(
                        f"  -> {item.agent_name or '(unknown)'}",
                        f"{item.total_interactions}",
                        f"{item.total_tokens.total:,}",
                        f"{item_avg:,}",
                        style="dim",
                    )

            self.console.print(model_table)
            self.console.print()

        # Agent -> Models table
        if omo_report.agent_model_breakdown:
            self.console.print(Rule("[bold cyan]Agent -> Models[/bold cyan]"))

            agent_models = defaultdict(list)
            for item in omo_report.agent_model_breakdown:
                agent_models[item.agent_name or "(unknown)"].append(item)

            agents_table = Table(show_header=True, header_style="bold blue")
            agents_table.add_column("Agent / Model", style="cyan")
            agents_table.add_column("Req", justify="right", style="green")
            agents_table.add_column("Total Tokens", justify="right", style="yellow")
            agents_table.add_column("Tok/Req", justify="right", style="dim")

            agent_totals = {}
            for agent, items in agent_models.items():
                agent_totals[agent] = sum(i.total_interactions for i in items)

            for agent in sorted(
                agent_totals.keys(), key=lambda a: agent_totals[a], reverse=True
            ):
                items = agent_models[agent]
                total_req = sum(i.total_interactions for i in items)
                total_tokens = sum(i.total_tokens.total for i in items)
                avg_tokens = total_tokens // total_req if total_req > 0 else 0

                agents_table.add_row(
                    f"[bold]{agent}[/bold]",
                    f"[bold]{total_req}[/bold]",
                    f"[bold]{total_tokens:,}[/bold]",
                    f"[bold]{avg_tokens:,}[/bold]",
                )

                for item in sorted(
                    items, key=lambda x: x.total_interactions, reverse=True
                ):
                    item_avg = (
                        item.total_tokens.total // item.total_interactions
                        if item.total_interactions > 0
                        else 0
                    )
                    agents_table.add_row(
                        f"  -> {item.model_name}",
                        f"{item.total_interactions}",
                        f"{item.total_tokens.total:,}",
                        f"{item_avg:,}",
                        style="dim",
                    )

            self.console.print(agents_table)
            self.console.print()

        # Category -> Models table (for subscription optimization)
        if omo_report.category_model_breakdown:
            self.console.print(Rule("[bold cyan]Category -> Models[/bold cyan]"))

            # Group by category
            cat_models = defaultdict(list)
            for item in omo_report.category_model_breakdown:
                cat_models[item.category_name].append(item)

            cat_model_table = Table(show_header=True, header_style="bold blue")
            cat_model_table.add_column("Category / Model", style="cyan")
            cat_model_table.add_column("Req", justify="right", style="green")
            cat_model_table.add_column("Total Tokens", justify="right", style="yellow")
            cat_model_table.add_column("Tok/Req", justify="right", style="dim")

            # Sort categories by total requests
            cat_totals = {}
            for cat, items in cat_models.items():
                cat_totals[cat] = sum(i.total_interactions for i in items)

            for cat in sorted(
                cat_totals.keys(), key=lambda c: cat_totals[c], reverse=True
            ):
                items = cat_models[cat]
                total_req = sum(i.total_interactions for i in items)
                total_tokens = sum(i.total_tokens.total for i in items)
                avg_tokens = total_tokens // total_req if total_req > 0 else 0

                cat_model_table.add_row(
                    f"[bold]{cat}[/bold]",
                    f"[bold]{total_req}[/bold]",
                    f"[bold]{total_tokens:,}[/bold]",
                    f"[bold]{avg_tokens:,}[/bold]",
                )

                # Model rows (indented)
                for item in sorted(
                    items, key=lambda x: x.total_interactions, reverse=True
                ):
                    item_avg = (
                        item.total_tokens.total // item.total_interactions
                        if item.total_interactions > 0
                        else 0
                    )
                    cat_model_table.add_row(
                        f"  -> {item.model_name}",
                        f"{item.total_interactions}",
                        f"{item.total_tokens.total:,}",
                        f"{item_avg:,}",
                        style="dim",
                    )

            self.console.print(cat_model_table)
            self.console.print()

        # Category -> Agents table (for workload analysis)
        if omo_report.category_agent_breakdown:
            self.console.print(Rule("[bold cyan]Category -> Agents[/bold cyan]"))

            # Group by category
            cat_agents = defaultdict(list)
            for item in omo_report.category_agent_breakdown:
                cat_agents[item.category_name].append(item)

            cat_agent_table = Table(show_header=True, header_style="bold blue")
            cat_agent_table.add_column("Category / Agent", style="cyan")
            cat_agent_table.add_column("Req", justify="right", style="green")
            cat_agent_table.add_column("Total Tokens", justify="right", style="yellow")
            cat_agent_table.add_column("Tok/Req", justify="right", style="dim")

            # Sort categories by total requests
            cat_agent_totals = {}
            for cat, items in cat_agents.items():
                cat_agent_totals[cat] = sum(i.total_interactions for i in items)

            for cat in sorted(
                cat_agent_totals.keys(), key=lambda c: cat_agent_totals[c], reverse=True
            ):
                items = cat_agents[cat]
                total_req = sum(i.total_interactions for i in items)
                total_tokens = sum(i.total_tokens.total for i in items)
                avg_tokens = total_tokens // total_req if total_req > 0 else 0

                cat_agent_table.add_row(
                    f"[bold]{cat}[/bold]",
                    f"[bold]{total_req}[/bold]",
                    f"[bold]{total_tokens:,}[/bold]",
                    f"[bold]{avg_tokens:,}[/bold]",
                )

                # Agent rows (indented)
                for item in sorted(
                    items, key=lambda x: x.total_interactions, reverse=True
                ):
                    item_avg = (
                        item.total_tokens.total // item.total_interactions
                        if item.total_interactions > 0
                        else 0
                    )
                    cat_agent_table.add_row(
                        f"  -> {item.agent_name or '(unknown)'}",
                        f"{item.total_interactions}",
                        f"{item.total_tokens.total:,}",
                        f"{item_avg:,}",
                        style="dim",
                    )

            self.console.print(cat_agent_table)
            self.console.print()

        # Categories table
        if omo_report.category_stats:
            self.console.print(
                Rule("[bold cyan]Categories (delegate_task)[/bold cyan]")
            )
            categories_table = Table(show_header=True, header_style="bold blue")
            categories_table.add_column("Category", style="cyan")
            categories_table.add_column("Req", justify="right", style="green")
            categories_table.add_column("In", justify="right", style="yellow")
            categories_table.add_column("Out", justify="right", style="yellow")
            categories_table.add_column("Models", style="dim")

            sorted_cats = sorted(
                omo_report.category_stats,
                key=lambda x: x.total_interactions,
                reverse=True,
            )
            for cat in sorted_cats:
                models_str = ", ".join(sorted(cat.models_used))
                categories_table.add_row(
                    cat.category_name or "(unknown)",
                    f"{cat.total_interactions}",
                    f"{cat.total_tokens.input:,}",
                    f"{cat.total_tokens.output:,}",
                    models_str,
                )

            self.console.print(categories_table)
            self.console.print()

        # Skills table (oh-my-opencode skills used with delegate_task)
        if omo_report.skill_stats:
            self.console.print(Rule("[bold cyan]Skills (delegate_task)[/bold cyan]"))
            skills_table = Table(show_header=True, header_style="bold blue")
            skills_table.add_column("Skill", style="cyan")
            skills_table.add_column("Req", justify="right", style="green")
            skills_table.add_column("Total Tokens", justify="right", style="yellow")
            skills_table.add_column("Tok/Req", justify="right", style="dim")
            skills_table.add_column("Agents", style="dim")
            skills_table.add_column("Categories", style="dim")

            sorted_skills = sorted(
                omo_report.skill_stats,
                key=lambda x: x.total_interactions,
                reverse=True,
            )
            for skill in sorted_skills:
                avg_tokens = (
                    skill.total_tokens.total // skill.total_interactions
                    if skill.total_interactions > 0
                    else 0
                )
                agents_str = ", ".join(sorted(skill.agents_used)[:3])
                if len(skill.agents_used) > 3:
                    agents_str += f" (+{len(skill.agents_used) - 3})"
                cats_str = ", ".join(sorted(skill.categories_used)[:3])
                if len(skill.categories_used) > 3:
                    cats_str += f" (+{len(skill.categories_used) - 3})"

                skills_table.add_row(
                    skill.skill_name,
                    f"{skill.total_interactions}",
                    f"{skill.total_tokens.total:,}",
                    f"{avg_tokens:,}",
                    agents_str,
                    cats_str,
                )

            self.console.print(skills_table)
            self.console.print()

    # JSON formatting methods
    def _format_single_session_json(
        self, session: SessionData, stats: Dict[str, Any], health: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format single session data as JSON."""
        return {
            "session_id": session.session_id,
            "session_title": session.session_title,
            "project_name": session.project_name,
            "statistics": {
                "interaction_count": stats["interaction_count"],
                "total_tokens": stats["total_tokens"].model_dump(),
                "total_cost": float(stats["total_cost"]),
                "models_used": stats["models_used"],
            },
            "health": health,
            "interactions": [
                {
                    "file_name": file.file_name,
                    "model_id": file.model_id,
                    "tokens": file.tokens.model_dump(),
                    "cost": float(file.calculate_cost(self.analyzer.pricing_data)),
                }
                for file in session.files
            ],
        }

    def _format_sessions_summary_json(
        self, sessions: List[SessionData], summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format sessions summary as JSON."""
        return {
            "summary": {
                "total_sessions": summary["total_sessions"],
                "total_interactions": summary["total_interactions"],
                "total_tokens": summary["total_tokens"].model_dump(),
                "total_cost": float(summary["total_cost"]),
                "models_used": summary["models_used"],
                "date_range": summary["date_range"],
            },
            "sessions": [
                {
                    "session_id": session.session_id,
                    "session_title": session.session_title,
                    "project_name": session.project_name,
                    "interaction_count": session.interaction_count,
                    "total_tokens": session.total_tokens.model_dump(),
                    "total_cost": float(
                        session.calculate_total_cost(self.analyzer.pricing_data)
                    ),
                    "models_used": session.models_used,
                    "start_time": session.start_time.isoformat()
                    if session.start_time
                    else None,
                    "end_time": session.end_time.isoformat()
                    if session.end_time
                    else None,
                }
                for session in sessions
            ],
        }

    def _format_daily_breakdown_json(
        self, daily_usage: List[DailyUsage]
    ) -> Dict[str, Any]:
        """Format daily breakdown as JSON."""
        return {
            "daily_breakdown": [
                {
                    "date": day.date.isoformat(),
                    "sessions": len(day.sessions),
                    "interactions": day.total_interactions,
                    "tokens": day.total_tokens.model_dump(),
                    "cost": float(day.calculate_total_cost(self.analyzer.pricing_data)),
                    "models_used": day.models_used,
                }
                for day in daily_usage
            ]
        }

    def _format_weekly_breakdown_json(
        self, weekly_usage: List[WeeklyUsage]
    ) -> Dict[str, Any]:
        """Format weekly breakdown as JSON."""
        return {
            "weekly_breakdown": [
                {
                    "year": week.year,
                    "week": week.week,
                    "start_date": week.start_date.isoformat(),
                    "end_date": week.end_date.isoformat(),
                    "sessions": week.total_sessions,
                    "interactions": week.total_interactions,
                    "tokens": week.total_tokens.model_dump(),
                    "cost": float(
                        week.calculate_total_cost(self.analyzer.pricing_data)
                    ),
                }
                for week in weekly_usage
            ]
        }

    def _format_monthly_breakdown_json(
        self, monthly_usage: List[MonthlyUsage]
    ) -> Dict[str, Any]:
        """Format monthly breakdown as JSON."""
        return {
            "monthly_breakdown": [
                {
                    "year": month.year,
                    "month": month.month,
                    "sessions": month.total_sessions,
                    "interactions": month.total_interactions,
                    "tokens": month.total_tokens.model_dump(),
                    "cost": float(
                        month.calculate_total_cost(self.analyzer.pricing_data)
                    ),
                }
                for month in monthly_usage
            ]
        }

    def _format_models_breakdown_json(
        self, model_breakdown: ModelBreakdownReport
    ) -> Dict[str, Any]:
        """Format models breakdown as JSON."""
        return {
            "timeframe": model_breakdown.timeframe,
            "start_date": model_breakdown.start_date.isoformat()
            if model_breakdown.start_date
            else None,
            "end_date": model_breakdown.end_date.isoformat()
            if model_breakdown.end_date
            else None,
            "total_cost": float(model_breakdown.total_cost),
            "total_tokens": model_breakdown.total_tokens.model_dump(),
            "models": [
                {
                    "model_name": model.model_name,
                    "sessions": model.total_sessions,
                    "interactions": model.total_interactions,
                    "tokens": model.total_tokens.model_dump(),
                    "cost": float(model.total_cost),
                    "first_used": model.first_used.isoformat()
                    if model.first_used
                    else None,
                    "last_used": model.last_used.isoformat()
                    if model.last_used
                    else None,
                }
                for model in model_breakdown.model_stats
            ],
        }

    # CSV formatting methods (returning data structures for export service)
    def _format_single_session_csv(
        self, session: SessionData, stats: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Format single session data for CSV export."""
        return [
            {
                "session_id": session.session_id,
                "session_title": session.session_title,
                "project_name": session.project_name,
                "file_name": file.file_name,
                "model_id": file.model_id,
                "input_tokens": file.tokens.input,
                "output_tokens": file.tokens.output,
                "cache_write_tokens": file.tokens.cache_write,
                "cache_read_tokens": file.tokens.cache_read,
                "total_tokens": file.tokens.total,
                "cost": float(file.calculate_cost(self.analyzer.pricing_data)),
                "duration_ms": file.time_data.duration_ms if file.time_data else None,
            }
            for file in session.files
        ]

    def _format_sessions_summary_csv(
        self, sessions: List[SessionData]
    ) -> List[Dict[str, Any]]:
        """Format sessions summary for CSV export."""
        rows = []
        for session in sessions:
            model_breakdown = session.get_model_breakdown(self.analyzer.pricing_data)
            for model, stats in model_breakdown.items():
                rows.append(
                    {
                        "session_id": session.session_id,
                        "session_title": session.session_title,
                        "project_name": session.project_name,
                        "start_time": session.start_time.isoformat()
                        if session.start_time
                        else None,
                        "duration_ms": session.duration_ms,
                        "model": model,
                        "interactions": stats["files"],
                        "input_tokens": stats["tokens"].input,
                        "output_tokens": stats["tokens"].output,
                        "cache_write_tokens": stats["tokens"].cache_write,
                        "cache_read_tokens": stats["tokens"].cache_read,
                        "total_tokens": stats["tokens"].total,
                        "cost": float(stats["cost"]),
                    }
                )
        return rows

    def _format_daily_breakdown_csv(
        self, daily_usage: List[DailyUsage]
    ) -> List[Dict[str, Any]]:
        """Format daily breakdown for CSV export."""
        return [
            {
                "date": day.date.isoformat(),
                "sessions": len(day.sessions),
                "interactions": day.total_interactions,
                "input_tokens": day.total_tokens.input,
                "output_tokens": day.total_tokens.output,
                "cache_write_tokens": day.total_tokens.cache_write,
                "cache_read_tokens": day.total_tokens.cache_read,
                "total_tokens": day.total_tokens.total,
                "cost": float(day.calculate_total_cost(self.analyzer.pricing_data)),
                "models_used": ", ".join(day.models_used),
            }
            for day in daily_usage
        ]

    def _format_weekly_breakdown_csv(
        self, weekly_usage: List[WeeklyUsage]
    ) -> List[Dict[str, Any]]:
        """Format weekly breakdown for CSV export."""
        return [
            {
                "year": week.year,
                "week": week.week,
                "start_date": week.start_date.isoformat(),
                "end_date": week.end_date.isoformat(),
                "sessions": week.total_sessions,
                "interactions": week.total_interactions,
                "input_tokens": week.total_tokens.input,
                "output_tokens": week.total_tokens.output,
                "cache_write_tokens": week.total_tokens.cache_write,
                "cache_read_tokens": week.total_tokens.cache_read,
                "total_tokens": week.total_tokens.total,
                "cost": float(week.calculate_total_cost(self.analyzer.pricing_data)),
            }
            for week in weekly_usage
        ]

    def _format_monthly_breakdown_csv(
        self, monthly_usage: List[MonthlyUsage]
    ) -> List[Dict[str, Any]]:
        """Format monthly breakdown for CSV export."""
        return [
            {
                "year": month.year,
                "month": month.month,
                "sessions": month.total_sessions,
                "interactions": month.total_interactions,
                "input_tokens": month.total_tokens.input,
                "output_tokens": month.total_tokens.output,
                "cache_write_tokens": month.total_tokens.cache_write,
                "cache_read_tokens": month.total_tokens.cache_read,
                "total_tokens": month.total_tokens.total,
                "cost": float(month.calculate_total_cost(self.analyzer.pricing_data)),
            }
            for month in monthly_usage
        ]

    def _format_models_breakdown_csv(
        self, model_breakdown: ModelBreakdownReport
    ) -> List[Dict[str, Any]]:
        """Format models breakdown for CSV export."""
        return [
            {
                "model_name": model.model_name,
                "sessions": model.total_sessions,
                "interactions": model.total_interactions,
                "input_tokens": model.total_tokens.input,
                "output_tokens": model.total_tokens.output,
                "cache_write_tokens": model.total_tokens.cache_write,
                "cache_read_tokens": model.total_tokens.cache_read,
                "total_tokens": model.total_tokens.total,
                "cost": float(model.total_cost),
                "first_used": model.first_used.isoformat()
                if model.first_used
                else None,
                "last_used": model.last_used.isoformat() if model.last_used else None,
            }
            for model in model_breakdown.model_stats
        ]

    def _format_projects_breakdown_json(
        self, project_breakdown: ProjectBreakdownReport
    ) -> Dict[str, Any]:
        """Format projects breakdown as JSON."""
        return {
            "timeframe": project_breakdown.timeframe,
            "start_date": project_breakdown.start_date.isoformat()
            if project_breakdown.start_date
            else None,
            "end_date": project_breakdown.end_date.isoformat()
            if project_breakdown.end_date
            else None,
            "total_cost": float(project_breakdown.total_cost),
            "total_tokens": project_breakdown.total_tokens.model_dump(),
            "projects": [
                {
                    "project_name": project.project_name,
                    "sessions": project.total_sessions,
                    "interactions": project.total_interactions,
                    "tokens": project.total_tokens.model_dump(),
                    "cost": float(project.total_cost),
                    "models_used": project.models_used,
                    "first_activity": project.first_activity.isoformat()
                    if project.first_activity
                    else None,
                    "last_activity": project.last_activity.isoformat()
                    if project.last_activity
                    else None,
                }
                for project in project_breakdown.project_stats
            ],
        }

    def _format_projects_breakdown_csv(
        self, project_breakdown: ProjectBreakdownReport
    ) -> List[Dict[str, Any]]:
        """Format projects breakdown for CSV export."""
        return [
            {
                "project_name": project.project_name,
                "sessions": project.total_sessions,
                "interactions": project.total_interactions,
                "input_tokens": project.total_tokens.input,
                "output_tokens": project.total_tokens.output,
                "cache_write_tokens": project.total_tokens.cache_write,
                "cache_read_tokens": project.total_tokens.cache_read,
                "total_tokens": project.total_tokens.total,
                "cost": float(project.total_cost),
                "models_used": ", ".join(project.models_used),
                "first_activity": project.first_activity.isoformat()
                if project.first_activity
                else None,
                "last_activity": project.last_activity.isoformat()
                if project.last_activity
                else None,
            }
            for project in project_breakdown.project_stats
        ]

    def _format_agents_breakdown_json(
        self,
        agent_breakdown: AgentBreakdownReport,
        agent_model_breakdown: Optional[List[AgentModelStats]] = None,
    ) -> Dict[str, Any]:
        """Format agents breakdown as JSON."""
        result = {
            "timeframe": agent_breakdown.timeframe,
            "start_date": agent_breakdown.start_date.isoformat()
            if agent_breakdown.start_date
            else None,
            "end_date": agent_breakdown.end_date.isoformat()
            if agent_breakdown.end_date
            else None,
            "total_cost": float(agent_breakdown.total_cost),
            "total_tokens": agent_breakdown.total_tokens.model_dump(),
            "agents": [
                {
                    "agent_name": agent.agent_name,
                    "sessions": agent.total_sessions,
                    "interactions": agent.total_interactions,
                    "tokens": agent.total_tokens.model_dump(),
                    "cost": float(agent.total_cost),
                    "models_used": agent.models_used,
                    "first_used": agent.first_used.isoformat()
                    if agent.first_used
                    else None,
                    "last_used": agent.last_used.isoformat()
                    if agent.last_used
                    else None,
                }
                for agent in agent_breakdown.agent_stats
            ],
        }

        if agent_model_breakdown:
            result["agent_model_breakdown"] = [
                {
                    "agent_name": item.agent_name,
                    "model_name": item.model_name,
                    "sessions": item.total_sessions,
                    "interactions": item.total_interactions,
                    "tokens": item.total_tokens.model_dump(),
                    "cost": float(item.total_cost),
                }
                for item in agent_model_breakdown
            ]

        return result

    def _format_agents_breakdown_csv(
        self,
        agent_breakdown: AgentBreakdownReport,
        agent_model_breakdown: Optional[List[AgentModelStats]] = None,
    ) -> List[Dict[str, Any]]:
        """Format agents breakdown for CSV export."""
        if agent_model_breakdown:
            # Return detailed agent × model breakdown
            return [
                {
                    "agent_name": item.agent_name,
                    "model_name": item.model_name,
                    "sessions": item.total_sessions,
                    "interactions": item.total_interactions,
                    "input_tokens": item.total_tokens.input,
                    "output_tokens": item.total_tokens.output,
                    "cache_write_tokens": item.total_tokens.cache_write,
                    "cache_read_tokens": item.total_tokens.cache_read,
                    "total_tokens": item.total_tokens.total,
                    "cost": float(item.total_cost),
                }
                for item in agent_model_breakdown
            ]
        else:
            return [
                {
                    "agent_name": agent.agent_name,
                    "sessions": agent.total_sessions,
                    "interactions": agent.total_interactions,
                    "input_tokens": agent.total_tokens.input,
                    "output_tokens": agent.total_tokens.output,
                    "cache_write_tokens": agent.total_tokens.cache_write,
                    "cache_read_tokens": agent.total_tokens.cache_read,
                    "total_tokens": agent.total_tokens.total,
                    "cost": float(agent.total_cost),
                    "models_used": ", ".join(agent.models_used),
                    "first_used": agent.first_used.isoformat()
                    if agent.first_used
                    else None,
                    "last_used": agent.last_used.isoformat()
                    if agent.last_used
                    else None,
                }
                for agent in agent_breakdown.agent_stats
            ]

    def _format_categories_breakdown_json(
        self, category_breakdown: CategoryBreakdownReport
    ) -> Dict[str, Any]:
        """Format categories breakdown as JSON."""
        return {
            "timeframe": category_breakdown.timeframe,
            "start_date": category_breakdown.start_date.isoformat()
            if category_breakdown.start_date
            else None,
            "end_date": category_breakdown.end_date.isoformat()
            if category_breakdown.end_date
            else None,
            "total_cost": float(category_breakdown.total_cost),
            "total_tokens": category_breakdown.total_tokens.model_dump(),
            "categories": [
                {
                    "category_name": category.category_name,
                    "sessions": category.total_sessions,
                    "interactions": category.total_interactions,
                    "tokens": category.total_tokens.model_dump(),
                    "cost": float(category.total_cost),
                    "models_used": category.models_used,
                    "first_used": category.first_used.isoformat()
                    if category.first_used
                    else None,
                    "last_used": category.last_used.isoformat()
                    if category.last_used
                    else None,
                }
                for category in category_breakdown.category_stats
            ],
        }

    def _format_categories_breakdown_csv(
        self, category_breakdown: CategoryBreakdownReport
    ) -> List[Dict[str, Any]]:
        """Format categories breakdown for CSV export."""
        return [
            {
                "category_name": category.category_name,
                "sessions": category.total_sessions,
                "interactions": category.total_interactions,
                "input_tokens": category.total_tokens.input,
                "output_tokens": category.total_tokens.output,
                "cache_write_tokens": category.total_tokens.cache_write,
                "cache_read_tokens": category.total_tokens.cache_read,
                "total_tokens": category.total_tokens.total,
                "cost": float(category.total_cost),
                "models_used": ", ".join(category.models_used),
                "first_used": category.first_used.isoformat()
                if category.first_used
                else None,
                "last_used": category.last_used.isoformat()
                if category.last_used
                else None,
            }
            for category in category_breakdown.category_stats
        ]

    def _format_skills_breakdown_json(
        self, skill_breakdown: SkillBreakdownReport
    ) -> Dict[str, Any]:
        """Format skills breakdown as JSON."""
        return {
            "timeframe": skill_breakdown.timeframe,
            "start_date": skill_breakdown.start_date.isoformat()
            if skill_breakdown.start_date
            else None,
            "end_date": skill_breakdown.end_date.isoformat()
            if skill_breakdown.end_date
            else None,
            "total_cost": float(skill_breakdown.total_cost),
            "total_tokens": skill_breakdown.total_tokens.model_dump(),
            "skills": [
                {
                    "skill_name": skill.skill_name,
                    "sessions": skill.total_sessions,
                    "interactions": skill.total_interactions,
                    "tokens": skill.total_tokens.model_dump(),
                    "cost": float(skill.total_cost),
                    "models_used": skill.models_used,
                    "agents_used": skill.agents_used,
                    "categories_used": skill.categories_used,
                    "first_used": skill.first_used.isoformat()
                    if skill.first_used
                    else None,
                    "last_used": skill.last_used.isoformat()
                    if skill.last_used
                    else None,
                }
                for skill in skill_breakdown.skill_stats
            ],
        }

    def _format_skills_breakdown_csv(
        self, skill_breakdown: SkillBreakdownReport
    ) -> List[Dict[str, Any]]:
        """Format skills breakdown for CSV export."""
        return [
            {
                "skill_name": skill.skill_name,
                "sessions": skill.total_sessions,
                "interactions": skill.total_interactions,
                "input_tokens": skill.total_tokens.input,
                "output_tokens": skill.total_tokens.output,
                "cache_write_tokens": skill.total_tokens.cache_write,
                "cache_read_tokens": skill.total_tokens.cache_read,
                "total_tokens": skill.total_tokens.total,
                "cost": float(skill.total_cost),
                "models_used": ", ".join(skill.models_used),
                "agents_used": ", ".join(skill.agents_used),
                "categories_used": ", ".join(skill.categories_used),
                "first_used": skill.first_used.isoformat()
                if skill.first_used
                else None,
                "last_used": skill.last_used.isoformat() if skill.last_used else None,
            }
            for skill in skill_breakdown.skill_stats
        ]

    def _format_omo_report_json(self, omo_report: OmoReport) -> Dict[str, Any]:
        """Format comprehensive oh-my-opencode report as JSON."""
        # Group by provider
        provider_usage = defaultdict(
            lambda: {
                "requests": 0,
                "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
            }
        )
        for model in omo_report.model_stats:
            provider = (
                model.model_name.split("/")[0] if "/" in model.model_name else "unknown"
            )
            provider_usage[provider]["requests"] += model.total_interactions
            provider_usage[provider]["tokens"]["input"] += model.total_tokens.input
            provider_usage[provider]["tokens"]["output"] += model.total_tokens.output
            provider_usage[provider]["tokens"]["cache_read"] += (
                model.total_tokens.cache_read
            )
            provider_usage[provider]["tokens"]["cache_write"] += (
                model.total_tokens.cache_write
            )

        return {
            "timeframe": omo_report.timeframe,
            "start_date": omo_report.start_date.isoformat()
            if omo_report.start_date
            else None,
            "end_date": omo_report.end_date.isoformat()
            if omo_report.end_date
            else None,
            "summary": {
                "total_sessions": omo_report.total_sessions,
                "total_requests": omo_report.total_interactions,
                "tokens": omo_report.total_tokens.model_dump(),
            },
            "providers": dict(provider_usage),
            "models": [
                {
                    "model": model.model_name,
                    "requests": model.total_interactions,
                    "tokens": model.total_tokens.model_dump(),
                }
                for model in sorted(
                    omo_report.model_stats,
                    key=lambda x: x.total_interactions,
                    reverse=True,
                )
            ],
            "agents": [
                {
                    "agent": agent.agent_name,
                    "requests": agent.total_interactions,
                    "tokens": agent.total_tokens.model_dump(),
                    "models": agent.models_used,
                }
                for agent in sorted(
                    omo_report.agent_stats,
                    key=lambda x: x.total_interactions,
                    reverse=True,
                )
            ],
            "categories": [
                {
                    "category": cat.category_name,
                    "requests": cat.total_interactions,
                    "tokens": cat.total_tokens.model_dump(),
                    "models": cat.models_used,
                }
                for cat in sorted(
                    omo_report.category_stats,
                    key=lambda x: x.total_interactions,
                    reverse=True,
                )
            ],
            "agent_model_breakdown": [
                {
                    "agent": item.agent_name,
                    "model": item.model_name,
                    "requests": item.total_interactions,
                    "tokens": item.total_tokens.model_dump(),
                }
                for item in omo_report.agent_model_breakdown
            ],
        }

    def _format_omo_report_csv(self, omo_report: OmoReport) -> List[Dict[str, Any]]:
        """Format comprehensive oh-my-opencode report for CSV export (agent × model breakdown)."""
        return [
            {
                "agent_name": item.agent_name,
                "model_name": item.model_name,
                "sessions": item.total_sessions,
                "interactions": item.total_interactions,
                "input_tokens": item.total_tokens.input,
                "output_tokens": item.total_tokens.output,
                "cache_write_tokens": item.total_tokens.cache_write,
                "cache_read_tokens": item.total_tokens.cache_read,
                "total_tokens": item.total_tokens.total,
                "cost": float(item.total_cost),
            }
            for item in omo_report.agent_model_breakdown
        ]

    # ==================== Limits Report Methods ====================

    def generate_limits_report(
        self,
        base_path: str,
        limits_config: Optional[LimitsConfig],
        window_hours: Optional[int] = None,
        output_format: str = "table",
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate subscription limits report.

        Args:
            base_path: Path to directory containing sessions
            limits_config: Subscription limits configuration
            window_hours: Override window hours for analysis
            output_format: Output format ("table", "json", "csv")
            project: Filter by project name (partial match)

        Returns:
            Report data
        """
        from datetime import datetime

        sessions = self.analyzer.analyze_all_sessions(base_path)

        # Apply project filter if specified
        if project:
            sessions = self.analyzer.filter_sessions_by_project(sessions, project)

        limits_analyzer = LimitsAnalyzer(limits_config, self.analyzer.pricing_data)
        limits_report = limits_analyzer.analyze_limits(
            sessions, window_hours_override=window_hours
        )

        report_data = {
            "type": "limits_report",
            "limits_report": limits_report,
            "generated_at": datetime.now().isoformat(),
        }

        if output_format == "table":
            self._display_limits_report_table(limits_report, limits_analyzer, sessions)
        elif output_format == "json":
            return self._format_limits_report_json(limits_report)
        elif output_format == "csv":
            return self._format_limits_report_csv(limits_report)

        return report_data

    def _display_limits_report_table(
        self,
        limits_report: LimitsReport,
        limits_analyzer: LimitsAnalyzer,
        sessions: List[SessionData],
    ):
        """Display subscription limits report as tables."""
        from rich.table import Table
        from rich.rule import Rule
        from rich.progress_bar import ProgressBar
        from rich.text import Text

        # Header
        self.console.print(
            Rule(f"[bold magenta]Subscription Limits Report[/bold magenta]")
        )
        self.console.print(
            f"[dim]Generated: {limits_report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
        )
        self.console.print()

        # Main limits table
        limits_table = Table(
            title="Provider Usage vs Limits",
            show_header=True,
            header_style="bold blue",
        )
        limits_table.add_column("Provider", style="cyan")
        limits_table.add_column("Window", justify="center", style="dim")
        limits_table.add_column("Requests", justify="right")
        limits_table.add_column("Req Limit", justify="right", style="dim")
        limits_table.add_column("Req %", justify="right")
        limits_table.add_column("Tokens", justify="right")
        limits_table.add_column("Tok Limit", justify="right", style="dim")
        limits_table.add_column("Status", justify="center")

        for usage in limits_report.provider_usage:
            # Format utilization with color coding
            def format_utilization(util: Optional[float]) -> str:
                if util is None:
                    return "-"
                if util >= 100:
                    return f"[bold red]{util:.0f}%[/bold red]"
                elif util >= 80:
                    return f"[yellow]{util:.0f}%[/yellow]"
                elif util >= 50:
                    return f"[white]{util:.0f}%[/white]"
                else:
                    return f"[green]{util:.0f}%[/green]"

            # Status indicator
            status_map = {
                "over": "[bold red]OVER[/bold red]",
                "warning": "[yellow]WARNING[/yellow]",
                "moderate": "[white]OK[/white]",
                "good": "[green]GOOD[/green]",
            }
            status = status_map.get(usage.utilization_status, "[dim]?[/dim]")

            # Format limits (show "-" for unlimited)
            req_limit_str = f"{usage.requests_limit:,}" if usage.requests_limit else "-"
            tok_limit_str = f"{usage.tokens_limit:,}" if usage.tokens_limit else "-"

            limits_table.add_row(
                usage.display_name or usage.provider_id,
                f"{usage.window_hours}h",
                f"{usage.requests_used:,}",
                req_limit_str,
                format_utilization(usage.requests_utilization),
                f"{usage.tokens_used:,}",
                tok_limit_str,
                status,
            )

        self.console.print(limits_table)
        self.console.print()

        # Per-model breakdown for providers with model-specific limits
        for usage in limits_report.provider_usage:
            if usage.models_used and len(usage.models_used) > 1:
                model_usage = limits_analyzer.analyze_model_limits(
                    sessions, usage.provider_id
                )
                if model_usage:
                    self.console.print(
                        Rule(
                            f"[bold cyan]{usage.display_name or usage.provider_id} - Model Breakdown[/bold cyan]"
                        )
                    )

                    model_table = Table(show_header=True, header_style="bold blue")
                    model_table.add_column("Model Pattern", style="cyan")
                    model_table.add_column("Requests", justify="right", style="green")
                    model_table.add_column("Limit", justify="right", style="dim")
                    model_table.add_column("Utilization", justify="right")
                    model_table.add_column("Models Matched", style="dim")

                    for pattern, data in model_usage.items():
                        limit = data.get("limit")
                        requests = data.get("requests", 0)
                        util = (requests / limit * 100) if limit and limit > 0 else None

                        util_str = "-"
                        if util is not None:
                            if util >= 100:
                                util_str = f"[bold red]{util:.0f}%[/bold red]"
                            elif util >= 80:
                                util_str = f"[yellow]{util:.0f}%[/yellow]"
                            else:
                                util_str = f"[green]{util:.0f}%[/green]"

                        models_matched = ", ".join(data.get("models_matched", [])[:3])
                        if len(data.get("models_matched", [])) > 3:
                            models_matched += "..."

                        model_table.add_row(
                            pattern,
                            f"{requests:,}",
                            f"{limit:,}" if limit else "-",
                            util_str,
                            models_matched,
                        )

                    self.console.print(model_table)
                    self.console.print()

        # Unconfigured providers warning
        if limits_report.unconfigured_providers:
            self.console.print(
                f"[yellow]⚠ Unconfigured providers (no limits set): "
                f"{', '.join(limits_report.unconfigured_providers)}[/yellow]"
            )
            self.console.print()

        # Recommendations
        if limits_report.recommendations:
            self.console.print(Rule("[bold cyan]Recommendations[/bold cyan]"))
            for rec in limits_report.recommendations:
                self.console.print(f"  • {rec}")
            self.console.print()

        # Providers over limit alert
        if limits_report.providers_over_limit:
            self.console.print(
                f"[bold red]🚨 OVER LIMIT: {', '.join(limits_report.providers_over_limit)}[/bold red]"
            )

        # Warning providers alert
        if limits_report.providers_warning:
            self.console.print(
                f"[yellow]⚠ HIGH USAGE (>80%): {', '.join(limits_report.providers_warning)}[/yellow]"
            )

    def _format_limits_report_json(self, limits_report: LimitsReport) -> Dict[str, Any]:
        """Format limits report as JSON."""
        return {
            "generated_at": limits_report.generated_at.isoformat(),
            "window_end": limits_report.window_end.isoformat(),
            "providers": [
                {
                    "provider_id": p.provider_id,
                    "display_name": p.display_name,
                    "window_hours": p.window_hours,
                    "requests_used": p.requests_used,
                    "requests_limit": p.requests_limit,
                    "requests_utilization": p.requests_utilization,
                    "requests_remaining": p.requests_remaining,
                    "tokens_used": p.tokens_used,
                    "tokens_limit": p.tokens_limit,
                    "tokens_utilization": p.tokens_utilization,
                    "cost_used": float(p.cost_used),
                    "monthly_cost_limit": float(p.monthly_cost_limit)
                    if p.monthly_cost_limit
                    else None,
                    "status": p.utilization_status,
                    "is_over_limit": p.is_over_limit,
                    "models_used": p.models_used,
                }
                for p in limits_report.provider_usage
            ],
            "unconfigured_providers": limits_report.unconfigured_providers,
            "providers_over_limit": limits_report.providers_over_limit,
            "providers_warning": limits_report.providers_warning,
            "recommendations": limits_report.recommendations,
        }

    def _format_limits_report_csv(
        self, limits_report: LimitsReport
    ) -> List[Dict[str, Any]]:
        """Format limits report as CSV rows."""
        return [
            {
                "provider_id": p.provider_id,
                "display_name": p.display_name or p.provider_id,
                "window_hours": p.window_hours,
                "requests_used": p.requests_used,
                "requests_limit": p.requests_limit or "",
                "requests_utilization_pct": round(p.requests_utilization, 1)
                if p.requests_utilization
                else "",
                "requests_remaining": p.requests_remaining or "",
                "tokens_used": p.tokens_used,
                "tokens_limit": p.tokens_limit or "",
                "tokens_utilization_pct": round(p.tokens_utilization, 1)
                if p.tokens_utilization
                else "",
                "cost_used": float(p.cost_used),
                "status": p.utilization_status,
                "is_over_limit": p.is_over_limit,
            }
            for p in limits_report.provider_usage
        ]
