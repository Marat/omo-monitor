"""Command line interface for OpenCode Monitor."""

import click
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, Any, Set
from typing_extensions import TypedDict


def get_spinner_name() -> str:
    """Get spinner name compatible with current platform.

    Returns ASCII-only spinner on Windows to avoid encoding issues.
    """
    if sys.platform == "win32":
        return "line"  # ASCII-only: - \ | /
    return "dots"  # Unicode dots (default)


class ProjectStatsEntry(TypedDict):
    paths: Set[str]
    sessions: int
    requests: int
    tokens: int


from rich.console import Console

from .config import config_manager
from .services.session_analyzer import SessionAnalyzer
from .services.report_generator import ReportGenerator
from .services.export_service import ExportService
from .services.live_monitor import LiveMonitor
from .utils.error_handling import (
    ErrorHandler,
    handle_errors,
    create_user_friendly_error,
)
from .utils.data_source import get_data_source, get_default_source
from . import __version__


def json_serializer(obj):
    """Custom JSON serializer for special types."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    else:
        return str(obj)


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config", "-c", type=click.Path(exists=True), help="Path to configuration file"
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option(
    "--source",
    "-s",
    type=click.Choice(["opencode", "claude-code", "codex", "crush", "all", "auto"]),
    default=None,
    help="Data source: opencode, claude-code, codex, crush, all (merged), or auto-detect",
)
@click.pass_context
def cli(ctx: click.Context, config: Optional[str], verbose: bool, source: Optional[str]):
    """OmO Monitor - Analytics and monitoring for AI coding sessions.

    Monitor token usage, costs, and performance metrics from your OpenCode
    and Claude Code AI coding sessions with beautiful tables and real-time dashboards.
    """
    # Initialize context object
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["console"] = Console()
    ctx.obj["error_handler"] = ErrorHandler(verbose=verbose)

    # Load configuration
    try:
        if config:
            config_manager.config_path = config
            config_manager.reload()

        ctx.obj["config"] = config_manager.config
        ctx.obj["pricing_data"] = config_manager.load_pricing_data()

        # Auto-sync Models.dev pricing (if enabled and cache is stale)
        pricing_config = ctx.obj["config"].pricing
        if pricing_config.source in ("models.dev", "both"):
            try:
                from .pricing import get_pricing_provider
                provider = get_pricing_provider(
                    source=pricing_config.source,
                    fallback_to_local=pricing_config.fallback_to_local,
                    cache_ttl_hours=pricing_config.cache_ttl_hours,
                )
                # This will use cached data if fresh, or fetch if stale
                provider.set_local_pricing(ctx.obj["pricing_data"])
                models_dev_pricing = provider.get_models_dev_client().fetch_pricing()
                if models_dev_pricing and verbose:
                    click.echo(f"[Pricing: {len(models_dev_pricing)} models from Models.dev]")
            except Exception:
                pass  # Non-fatal, continue with local pricing

        # Initialize data source
        if source:
            ctx.obj["data_source"] = get_data_source(source)
        else:
            ctx.obj["data_source"] = get_default_source()
        ctx.obj["source_name"] = ctx.obj["data_source"].name

        # Initialize services
        analyzer = SessionAnalyzer(
            ctx.obj["pricing_data"],
            data_source=ctx.obj["data_source"],
        )
        ctx.obj["analyzer"] = analyzer
        ctx.obj["report_generator"] = ReportGenerator(analyzer, ctx.obj["console"])
        ctx.obj["export_service"] = ExportService(ctx.obj["config"].paths.export_dir)
        ctx.obj["limits_config"] = config_manager.load_limits_config()
        ctx.obj["live_monitor"] = LiveMonitor(
            ctx.obj["pricing_data"],
            ctx.obj["console"],
            session_max_hours=ctx.obj["config"].ui.session_max_hours,
            limits_config=ctx.obj["limits_config"],
            data_source=ctx.obj["data_source"],
        )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error initializing OmO Monitor: {error_msg}", err=True)
        if verbose:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def session(ctx: click.Context, path: Optional[str], output_format: str):
    """Analyze a single OpenCode session directory.

    PATH: Path to session directory (defaults to current directory)
    """
    if not path:
        path = str(Path.cwd())

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_single_session_report(path, output_format)

        if result is None:
            click.echo(
                "No valid session data found in the specified directory.", err=True
            )
            ctx.exit(1)

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error analyzing session: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option(
    "--limit", "-l", type=int, default=None, help="Limit number of sessions to analyze"
)
@click.pass_context
def sessions(
    ctx: click.Context, path: Optional[str], output_format: str, limit: Optional[int]
):
    """Analyze all sessions from configured data source.

    PATH: Path to directory containing session folders
          (defaults to configured directory for the active data source)

    Use --source to switch between opencode, claude-code, all, or auto.
    """
    config = ctx.obj["config"]
    source_name = ctx.obj.get("source_name", "opencode")

    # Path is optional - data source will use its default
    if not path and source_name == "opencode":
        path = config.paths.messages_dir

    try:
        analyzer = ctx.obj["analyzer"]
        report_generator = ctx.obj["report_generator"]

        # Show data source info
        click.echo(f"[Source: {source_name}]")

        if limit:
            sessions = analyzer.analyze_all_sessions(path, limit)
            click.echo(f"Analyzing {len(sessions)} most recent sessions...")
        else:
            sessions = analyzer.analyze_all_sessions(path)
            click.echo(f"Analyzing {len(sessions)} sessions...")

        if not sessions:
            click.echo("No sessions found.", err=True)
            ctx.exit(1)

        result = report_generator.generate_sessions_summary_report(
            path, limit, output_format
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error analyzing sessions: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--interval", "-i", type=int, default=None, help="Update interval in seconds"
)
@click.option(
    "--project",
    "-p",
    type=str,
    help="Filter by project name (partial match). Use 'all' for aggregate view.",
)
@click.option(
    "--hours",
    "-H",
    type=int,
    default=None,
    help="Show data from last N hours (default: today only)",
)
@click.option(
    "--minutes",
    "-m",
    type=int,
    default=None,
    help="Show data from last N minutes (use 0 to start fresh for testing)",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.pass_context
def live(
    ctx: click.Context,
    path: Optional[str],
    interval: Optional[int],
    project: Optional[str],
    hours: Optional[int],
    minutes: Optional[int],
    no_color: bool,
):
    """Start live dashboard for monitoring the most recent session.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)

    Use --project to lock monitoring to a specific project and prevent
    jumping between projects when other sessions are active.

    Use --project all for aggregate statistics across all projects.

    Use --minutes 0 to start with no history (fresh start for testing).
    """
    config = ctx.obj["config"]
    data_source = ctx.obj["data_source"]

    # Set defaults and ensure non-None types
    # Use data source's default path, fallback to OpenCode messages_dir
    default_path = data_source.default_path or config.paths.messages_dir
    actual_path: str = path if path else default_path
    actual_interval: int = (
        interval if interval is not None else config.ui.live_refresh_interval
    )

    # Convert minutes to hours (float) if specified
    # minutes takes precedence over hours
    # minutes=0 means start fresh (no history)
    hours_filter: Optional[float] = None
    time_filter_display = "today only"

    if minutes is not None:
        if minutes == 0:
            # Special case: start fresh with no history
            hours_filter = 0.0001  # ~0.36 seconds - effectively "now"
            time_filter_display = "fresh start (no history)"
        else:
            hours_filter = minutes / 60.0
            time_filter_display = f"last {minutes} minutes"
    elif hours is not None:
        hours_filter = float(hours)
        time_filter_display = f"last {hours} hours"

    try:
        live_monitor = ctx.obj["live_monitor"]

        # Validate monitoring setup
        validation = live_monitor.validate_monitoring_setup(actual_path)
        if not validation["valid"]:
            for issue in validation["issues"]:
                click.echo(f"Error: {issue}", err=True)
            ctx.exit(1)

        if validation["warnings"]:
            for warning in validation["warnings"]:
                click.echo(f"Warning: {warning}")

        # Use Rich console for proper markup rendering
        # If no_color is set, create a colorless console
        if no_color:
            from rich.console import Console

            console = Console(no_color=True, force_terminal=True)
            # Create a new live monitor with the colorless console
            from .services.live_monitor import LiveMonitor

            live_monitor = LiveMonitor(
                ctx.obj["pricing_data"],
                console,
                session_max_hours=config.ui.session_max_hours,
                limits_config=ctx.obj["limits_config"],
                data_source=ctx.obj["data_source"],
            )
        else:
            console = ctx.obj["console"]

        # Use Textual-based monitor for aggregate view
        if project and project.lower() in ("all", "*"):
            from .services.textual_monitor import run_textual_monitor

            run_textual_monitor(
                base_path=actual_path,
                pricing_data=ctx.obj["pricing_data"],
                limits_config=ctx.obj["limits_config"],
                refresh_interval=actual_interval,
                hours_filter=hours_filter,
                data_source=ctx.obj["data_source"],
            )
        else:
            console.print("[green]Starting live dashboard...[/green]")
            console.print(f"Monitoring: {actual_path}")
            if project:
                console.print(f"[cyan]Project filter: {project}[/cyan]")
            console.print(f"[cyan]Time filter: {time_filter_display}[/cyan]")
            console.print(f"Update interval: {actual_interval}s")

            live_monitor.start_monitoring(
                actual_path, actual_interval, project_filter=project
            )

    except KeyboardInterrupt:
        # Already handled in start_monitoring, just exit cleanly
        pass
    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error in live monitoring: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option("--month", type=str, help="Month to analyze (YYYY-MM format)")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--breakdown", is_flag=True, help="Show per-model breakdown")
@click.pass_context
def daily(
    ctx: click.Context,
    path: Optional[str],
    month: Optional[str],
    output_format: str,
    breakdown: bool,
):
    """Show daily breakdown of OpenCode usage.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_daily_report(
            path, month, output_format, breakdown
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating daily breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option("--year", type=int, help="Year to analyze")
@click.option(
    "--start-day",
    type=click.Choice(
        ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
        case_sensitive=False,
    ),
    default="monday",
    help="Day to start the week (default: monday)",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--breakdown", is_flag=True, help="Show per-model breakdown")
@click.pass_context
def weekly(
    ctx: click.Context,
    path: Optional[str],
    year: Optional[int],
    start_day: str,
    output_format: str,
    breakdown: bool,
):
    """Show weekly breakdown of OpenCode usage.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)

    Examples:
        omo-monitor weekly                    # Default (Monday start)
        omo-monitor weekly --start-day sunday # Sunday to Sunday weeks
        omo-monitor weekly --start-day friday # Friday to Friday weeks
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    # Convert day name to weekday number
    from .utils.time_utils import WEEKDAY_MAP

    week_start_day = WEEKDAY_MAP[start_day.lower()]

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_weekly_report(
            path, year, output_format, breakdown, week_start_day
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating weekly breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option("--year", type=int, help="Year to analyze")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--breakdown", is_flag=True, help="Show per-model breakdown")
@click.pass_context
def monthly(
    ctx: click.Context,
    path: Optional[str],
    year: Optional[int],
    output_format: str,
    breakdown: bool,
):
    """Show monthly breakdown of OpenCode usage.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_monthly_report(
            path, year, output_format, breakdown
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating monthly breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--timeframe",
    type=click.Choice(["daily", "weekly", "monthly", "all"]),
    default="all",
    help="Timeframe for analysis",
)
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def models(
    ctx: click.Context,
    path: Optional[str],
    timeframe: str,
    start_date: Optional[str],
    end_date: Optional[str],
    project: Optional[str],
    output_format: str,
):
    """Show model usage breakdown and statistics.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_models_report(
            path, timeframe, start_date, end_date, output_format, project
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating model breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--timeframe",
    type=click.Choice(["daily", "weekly", "monthly", "all"]),
    default="all",
    help="Timeframe for analysis",
)
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def projects(
    ctx: click.Context,
    path: Optional[str],
    timeframe: str,
    start_date: Optional[str],
    end_date: Optional[str],
    output_format: str,
):
    """Show project usage breakdown and statistics.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_projects_report(
            path, timeframe, start_date, end_date, output_format
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating project breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--timeframe",
    type=click.Choice(["daily", "weekly", "monthly", "all"]),
    default="all",
    help="Timeframe for analysis",
)
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option(
    "--breakdown", "-b", is_flag=True, help="Show detailed agent x model breakdown"
)
@click.pass_context
def agents(
    ctx: click.Context,
    path: Optional[str],
    timeframe: str,
    start_date: Optional[str],
    end_date: Optional[str],
    project: Optional[str],
    output_format: str,
    breakdown: bool,
):
    """Show agent usage breakdown (oh-my-opencode agents like explore, oracle, etc).

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)

    Use --breakdown to see detailed agent x model statistics.
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_agents_report(
            path, timeframe, start_date, end_date, output_format, breakdown, project
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating agent breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--timeframe",
    type=click.Choice(["daily", "weekly", "monthly", "all"]),
    default="all",
    help="Timeframe for analysis",
)
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def categories(
    ctx: click.Context,
    path: Optional[str],
    timeframe: str,
    start_date: Optional[str],
    end_date: Optional[str],
    project: Optional[str],
    output_format: str,
):
    """Show delegate_task category usage breakdown (bugfix, algorithm, etc).

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_categories_report(
            path, timeframe, start_date, end_date, output_format, project
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating category breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--timeframe",
    type=click.Choice(["daily", "weekly", "monthly", "all"]),
    default="all",
    help="Timeframe for analysis",
)
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option("--today", "period_preset", flag_value="today", help="Show today only")
@click.option("--week", "period_preset", flag_value="week", help="Show last 7 days")
@click.option("--month", "period_preset", flag_value="month", help="Show last 30 days")
@click.option("--days", "-d", type=int, help="Show last N days")
@click.option("--hours", "-H", type=int, help="Show last N hours")
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def skills(
    ctx: click.Context,
    path: Optional[str],
    timeframe: str,
    start_date: Optional[str],
    end_date: Optional[str],
    period_preset: Optional[str],
    days: Optional[int],
    hours: Optional[int],
    project: Optional[str],
    output_format: str,
):
    """Show skill usage breakdown (oh-my-opencode skills like playwright, git-master, etc).

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)

    Period options:
      --today           Today only
      --week            Last 7 days
      --month           Last 30 days
      --days N / -d N   Last N days
      --hours N / -H N  Last N hours
      --start-date/--end-date  Custom range (YYYY-MM-DD)

    Skills are injected via delegate_task and influence model selection.
    """
    from datetime import date, timedelta, datetime as dt

    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    # Handle period presets and custom periods
    start_datetime_filter = None  # For precise hour filtering

    if hours:
        now = dt.now()
        start_datetime_filter = now - timedelta(hours=hours)
        click.echo(
            f"[Filter: last {hours} hours from {start_datetime_filter.strftime('%Y-%m-%d %H:%M')}]"
        )
    elif days:
        today = date.today()
        start_date = (today - timedelta(days=days - 1)).isoformat()
        end_date = today.isoformat()
        click.echo(f"[Filter: last {days} days]")
    elif period_preset == "today":
        today = date.today()
        start_date = today.isoformat()
        end_date = today.isoformat()
        click.echo("[Filter: today]")
    elif period_preset == "week":
        today = date.today()
        start_date = (today - timedelta(days=6)).isoformat()
        end_date = today.isoformat()
        click.echo("[Filter: last 7 days]")
    elif period_preset == "month":
        today = date.today()
        start_date = (today - timedelta(days=29)).isoformat()
        end_date = today.isoformat()
        click.echo("[Filter: last 30 days]")

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_skills_report(
            path,
            timeframe,
            start_date,
            end_date,
            output_format,
            project,
            start_datetime=start_datetime_filter,
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating skill breakdown: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--timeframe",
    type=click.Choice(["daily", "weekly", "monthly", "all"]),
    default="all",
    help="Timeframe for analysis",
)
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option("--today", "period_preset", flag_value="today", help="Show today only")
@click.option("--week", "period_preset", flag_value="week", help="Show last 7 days")
@click.option("--month", "period_preset", flag_value="month", help="Show last 30 days")
@click.option("--days", "-d", type=int, help="Show last N days")
@click.option("--hours", "-H", type=int, help="Show last N hours")
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def omo(
    ctx: click.Context,
    path: Optional[str],
    timeframe: str,
    start_date: Optional[str],
    end_date: Optional[str],
    period_preset: Optional[str],
    days: Optional[int],
    hours: Optional[int],
    project: Optional[str],
    output_format: str,
):
    """Comprehensive oh-my-opencode usage report.

    Shows all statistics in one view:
    - Overall summary (sessions, requests, tokens)
    - Provider/subscription usage breakdown
    - Model usage (full provider/model ID)
    - Agent -> Model hierarchy
    - Category usage (delegate_task)

    Period options:
      --today           Today only
      --week            Last 7 days
      --month           Last 30 days
      --days N / -d N   Last N days
      --hours N / -H N  Last N hours
      --start-date/--end-date  Custom range (YYYY-MM-DD)

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    from datetime import date, timedelta, datetime as dt

    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    # Handle period presets and custom periods
    start_datetime_filter = None  # For precise hour filtering

    if hours:
        # For hours, we need datetime precision - use start_datetime
        now = dt.now()
        start_datetime_filter = now - timedelta(hours=hours)
        # Don't set start_date/end_date when using hours - let start_datetime handle it
        # Show info about hours filter
        click.echo(
            f"[Filter: last {hours} hours from {start_datetime_filter.strftime('%Y-%m-%d %H:%M')}]"
        )
    elif days:
        today = date.today()
        start_date = (today - timedelta(days=days - 1)).isoformat()
        end_date = today.isoformat()
    elif period_preset:
        today = date.today()
        if period_preset == "today":
            start_date = today.isoformat()
            end_date = today.isoformat()
        elif period_preset == "week":
            start_date = (today - timedelta(days=6)).isoformat()
            end_date = today.isoformat()
        elif period_preset == "month":
            start_date = (today - timedelta(days=29)).isoformat()
            end_date = today.isoformat()

    # Show project filter info
    if project:
        click.echo(f"[Filter: project contains '{project}']")

    try:
        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_omo_report(
            path,
            timeframe,
            start_date,
            end_date,
            output_format,
            start_datetime_filter,
            project,
        )

        if output_format == "json":
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating oh-my-opencode report: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command("projects-list")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option("--today", "period_preset", flag_value="today", help="Show today only")
@click.option("--week", "period_preset", flag_value="week", help="Show last 7 days")
@click.option("--month", "period_preset", flag_value="month", help="Show last 30 days")
@click.option("--days", "-d", type=int, help="Show last N days")
@click.option("--hours", "-H", type=int, help="Show last N hours")
@click.option("--start-date", type=str, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, help="End date (YYYY-MM-DD)")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def projects_list(
    ctx: click.Context,
    path: Optional[str],
    period_preset: Optional[str],
    days: Optional[int],
    hours: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    output_format: str,
):
    """List all projects with usage statistics for a period.

    Shows unique projects found in sessions with:
    - Project name (directory name)
    - Full path
    - Session count
    - Request count
    - Total tokens

    Period options:
      --today           Today only
      --week            Last 7 days
      --month           Last 30 days
      --days N / -d N   Last N days
      --hours N / -H N  Last N hours
      --start-date/--end-date  Custom range (YYYY-MM-DD)

    Use with `omo-monitor omo --project <name>` to filter reports by project.

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)
    """
    from datetime import date, timedelta, datetime as dt
    from collections import defaultdict
    from rich.table import Table

    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    # Handle period presets
    start_datetime_filter = None

    if hours:
        now = dt.now()
        start_datetime_filter = now - timedelta(hours=hours)
        click.echo(
            f"[Filter: last {hours} hours from {start_datetime_filter.strftime('%Y-%m-%d %H:%M')}]"
        )
    elif days:
        today = date.today()
        start_date = (today - timedelta(days=days - 1)).isoformat()
        end_date = today.isoformat()
    elif period_preset:
        today = date.today()
        if period_preset == "today":
            start_date = today.isoformat()
            end_date = today.isoformat()
        elif period_preset == "week":
            start_date = (today - timedelta(days=6)).isoformat()
            end_date = today.isoformat()
        elif period_preset == "month":
            start_date = (today - timedelta(days=29)).isoformat()
            end_date = today.isoformat()

    try:
        analyzer = ctx.obj["analyzer"]
        sessions = analyzer.analyze_all_sessions(path)

        # Parse date filters and filter sessions
        from .utils.time_utils import TimeUtils

        parsed_start_date = (
            TimeUtils.parse_date_string(start_date) if start_date else None
        )
        parsed_end_date = TimeUtils.parse_date_string(end_date) if end_date else None

        if parsed_start_date or parsed_end_date:
            sessions = analyzer.filter_sessions_by_date(
                sessions, parsed_start_date, parsed_end_date
            )

        # For hours filter, filter by file timestamps
        if start_datetime_filter:
            filtered_sessions = []
            for session in sessions:
                has_recent_files = any(
                    f.time_data
                    and f.time_data.created_datetime
                    and f.time_data.created_datetime >= start_datetime_filter
                    for f in session.files
                )
                if has_recent_files:
                    filtered_sessions.append(session)
            sessions = filtered_sessions

        # Aggregate by project
        # Using explicit dict with TypedDict for type safety
        project_stats: Dict[str, ProjectStatsEntry] = {}

        for session in sessions:
            project_name = session.project_name
            if project_name == "Unknown":
                continue

            # Initialize project stats if not exists
            if project_name not in project_stats:
                project_stats[project_name] = ProjectStatsEntry(
                    paths=set(),
                    sessions=0,
                    requests=0,
                    tokens=0,
                )

            # Get full paths from files
            for file in session.files:
                if file.project_path:
                    project_stats[project_name]["paths"].add(file.project_path)

            project_stats[project_name]["sessions"] += 1
            project_stats[project_name]["requests"] += session.interaction_count
            project_stats[project_name]["tokens"] += session.total_tokens.total

        if output_format == "json":
            result = {
                "projects": [
                    {
                        "name": name,
                        "paths": list(stats["paths"]),
                        "sessions": stats["sessions"],
                        "requests": stats["requests"],
                        "tokens": stats["tokens"],
                    }
                    for name, stats in sorted(
                        project_stats.items(),
                        key=lambda x: x[1]["tokens"],
                        reverse=True,
                    )
                ]
            }
            click.echo(json.dumps(result, indent=2, default=json_serializer))
        else:
            console = ctx.obj["console"]

            if not project_stats:
                console.print("[dim]No projects found for the specified period.[/dim]")
                return

            table = Table(title="Projects", show_header=True, header_style="bold blue")
            table.add_column("Project", style="cyan")
            table.add_column("Path", style="dim")
            table.add_column("Sessions", justify="right", style="green")
            table.add_column("Requests", justify="right", style="yellow")
            table.add_column("Tokens", justify="right", style="bold white")

            for name, stats in sorted(
                project_stats.items(), key=lambda x: x[1]["tokens"], reverse=True
            ):
                # Get shortest path for display
                paths = list(stats["paths"])
                display_path = min(paths, key=len) if paths else "-"
                if len(display_path) > 50:
                    display_path = "..." + display_path[-47:]

                table.add_row(
                    name,
                    display_path,
                    str(stats["sessions"]),
                    str(stats["requests"]),
                    f"{stats['tokens']:,}",
                )

            console.print(table)
            console.print()
            console.print(
                f"[dim]Use [cyan]omo-monitor omo --project <name>[/cyan] to filter reports by project[/dim]"
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error listing projects: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--hours",
    "-H",
    type=int,
    help="Show usage for last N hours (default: use provider window)",
)
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.pass_context
def limits(
    ctx: click.Context,
    path: Optional[str],
    hours: Optional[int],
    project: Optional[str],
    output_format: str,
):
    """Show subscription limits and current usage.

    Analyzes usage against configured subscription limits.
    Each provider has its own rolling time window (typically 5 hours).

    Configure limits in ~/.config/omo-monitor/limits.yaml

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)

    Examples:
        omo-monitor limits                     # Show current usage vs limits
        omo-monitor limits --hours 5           # Show last 5 hours specifically
        omo-monitor limits -p myproject        # Filter by project name
        omo-monitor limits -f json             # Output as JSON
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    try:
        # Load limits configuration
        limits_config = config_manager.load_limits_config()

        if not limits_config:
            click.echo("[yellow]⚠ No limits configuration found.[/yellow]")
            click.echo(
                "Create ~/.config/omo-monitor/limits.yaml to track subscription limits."
            )
            click.echo()
            click.echo("Example configuration:")
            click.echo("""
providers:
  - provider_id: anthropic
    display_name: "Anthropic MAX"
    monthly_cost_limit: 200.00
    
  - provider_id: google
    display_name: "Antigravity (10 accounts)"
    window_hours: 5
    account_count: 10
    model_limits:
      - model_pattern: "antigravity-claude-*"
        requests_per_window: 250
      - model_pattern: "antigravity-gemini-3-pro*"
        requests_per_window: 400
""")
            # Still show usage even without limits
            click.echo()
            click.echo("[dim]Showing raw provider usage (no limits configured):[/dim]")

        # Show project filter info if specified
        if project:
            click.echo(f"[Filter: project '{project}']")

        report_generator = ctx.obj["report_generator"]
        result = report_generator.generate_limits_report(
            path, limits_config, hours, output_format, project
        )

        if output_format == "json":
            import json

            click.echo(json.dumps(result, indent=2, default=json_serializer))
        elif output_format == "csv":
            click.echo(
                "CSV data would be exported to file. Use 'export' command for file output."
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating limits report: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--hours", "-H", type=int, default=24, help="Analysis window in hours (default: 24)"
)
@click.option(
    "--project", "-p", type=str, help="Filter by project name (partial match)"
)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Apply recommendations to oh-my-opencode.json",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=True,
    help="Show changes without applying (default)",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def optimize(
    ctx: click.Context,
    path: Optional[str],
    hours: int,
    project: Optional[str],
    apply_changes: bool,
    dry_run: bool,
    output_format: str,
):
    """Analyze usage and suggest optimizations for load redistribution.

    Examines which agents/categories use expensive providers (like Anthropic)
    and recommends moving them to underutilized providers (like Antigravity).

    PATH: Path to directory containing session folders
          (defaults to configured messages directory)

    Examples:
        omo-monitor optimize                       # Show recommendations
        omo-monitor optimize --hours 5             # Analyze last 5 hours
        omo-monitor optimize -p myproject          # Filter by project name
        omo-monitor optimize --apply               # Apply recommendations to config
        omo-monitor optimize -f json               # Output as JSON
    """
    from rich.console import Console
    from rich.table import Table
    from rich.rule import Rule
    from rich.panel import Panel

    config = ctx.obj["config"]
    console = Console()

    if not path:
        path = config.paths.messages_dir

    try:
        # Load limits configuration
        limits_config = config_manager.load_limits_config()
        pricing_data = ctx.obj["pricing_data"]

        # Import analyzer
        from .services.limits_analyzer import LimitsAnalyzer

        limits_analyzer = LimitsAnalyzer(limits_config, pricing_data)

        # Load sessions
        from .services.session_analyzer import SessionAnalyzer

        session_analyzer = SessionAnalyzer(pricing_data)

        # Ensure path is not None
        analysis_path = path if path else config.paths.messages_dir
        sessions = session_analyzer.analyze_all_sessions(analysis_path)

        # Apply project filter if specified
        if project:
            sessions = session_analyzer.filter_sessions_by_project(sessions, project)
            console.print(f"[dim][Filter: project '{project}'][/dim]")

        # Generate recommendations
        recommendations = limits_analyzer.generate_routing_recommendations(
            sessions, hours=hours
        )

        if output_format == "json":
            import json

            click.echo(json.dumps(recommendations, indent=2, default=json_serializer))
            return

        # Display header
        console.print(Rule("[bold magenta]Optimization Recommendations[/bold magenta]"))
        console.print(f"[dim]Analysis period: last {hours} hours[/dim]")
        console.print()

        # Show Antigravity capacity summary
        console.print(Rule("[bold cyan]Antigravity Capacity (10 accounts)[/bold cyan]"))
        capacity_table = Table(show_header=True, header_style="bold blue")
        capacity_table.add_column("Model", style="cyan")
        capacity_table.add_column("Capacity", justify="right", style="green")
        capacity_table.add_column("Window", justify="center", style="yellow")
        capacity_table.add_column("Best For", style="dim")

        capacity_table.add_row(
            "Claude Opus Thinking",
            "2,500 req",
            "[red]24h[/red]",
            "Very complex reasoning",
        )
        capacity_table.add_row(
            "Claude Sonnet Thinking",
            "2,500 req",
            "5h",
            "Complex reasoning with thinking",
        )
        capacity_table.add_row(
            "Gemini 3 Pro High", "4,000 req", "5h", "Complex coding tasks"
        )
        capacity_table.add_row(
            "Gemini 3 Pro", "4,000 req", "5h", "Standard coding tasks"
        )
        capacity_table.add_row(
            "Gemini 3 Flash", "30,000 req", "5h", "Fast, high-volume tasks"
        )
        console.print(capacity_table)
        console.print()

        if not recommendations:
            console.print(
                "[green]✓ No optimization recommendations - usage is well balanced![/green]"
            )
            return

        # Show recommendations table
        console.print(Rule("[bold cyan]Recommendations[/bold cyan]"))
        rec_table = Table(show_header=True, header_style="bold blue")
        rec_table.add_column("Agent/Category", style="cyan")
        rec_table.add_column("Current", style="red")
        rec_table.add_column("Suggested", style="green")
        rec_table.add_column("Requests", justify="right")
        rec_table.add_column("Impact", justify="center")
        rec_table.add_column("Reason", style="dim", max_width=40)

        total_movable = 0
        for rec in recommendations:
            impact_style = {
                "high": "[bold red]HIGH[/bold red]",
                "medium": "[yellow]MEDIUM[/yellow]",
                "low": "[green]LOW[/green]",
            }.get(rec["impact"], rec["impact"])

            rec_table.add_row(
                f"[{rec['type']}] {rec['name']}",
                rec["current_model"] or rec["current_provider"],
                rec["suggested_model"].split("/")[-1],  # Short model name
                f"{rec['requests_moved']:,}",
                impact_style,
                rec["reason"],
            )
            total_movable += rec["requests_moved"]

        console.print(rec_table)
        console.print()
        console.print(
            f"[bold]Total requests that could be moved: {total_movable:,}[/bold]"
        )
        console.print()

        # Apply changes if requested
        if apply_changes and not dry_run:
            console.print(Rule("[bold yellow]Applying Changes[/bold yellow]"))
            modified_config, summary = limits_analyzer.apply_routing_recommendations(
                recommendations, dry_run=False
            )
            console.print(summary)
        else:
            console.print(
                "[dim]Use --apply to apply these recommendations to oh-my-opencode.json[/dim]"
            )

            # Show what would change
            _, summary = limits_analyzer.apply_routing_recommendations(
                recommendations, dry_run=True
            )
            console.print()
            console.print(
                Panel(summary, title="Proposed Changes", border_style="yellow")
            )

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error generating optimization report: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.command()
@click.argument(
    "report_type",
    type=click.Choice(
        [
            "session",
            "sessions",
            "daily",
            "weekly",
            "monthly",
            "models",
            "projects",
            "agents",
            "categories",
            "omo",
            "limits",
        ]
    ),
)
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "--format",
    "-f",
    "export_format",
    type=click.Choice(["csv", "json"]),
    help="Export format (defaults to configured format)",
)
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--include-raw", is_flag=True, help="Include raw data in export")
@click.pass_context
def export(
    ctx: click.Context,
    report_type: str,
    path: Optional[str],
    export_format: Optional[str],
    output: Optional[str],
    include_raw: bool,
):
    """Export analysis results to file.

    REPORT_TYPE: Type of report to export
    PATH: Path to analyze (defaults to configured messages directory)
    """
    config = ctx.obj["config"]

    if not path:
        path = config.paths.messages_dir

    if not export_format:
        export_format = config.export.default_format

    try:
        report_generator = ctx.obj["report_generator"]
        export_service = ctx.obj["export_service"]

        # Generate report data
        report_data = None
        if report_type == "session":
            report_data = report_generator.generate_single_session_report(path, "json")
        elif report_type == "sessions":
            report_data = report_generator.generate_sessions_summary_report(
                path, None, "table"
            )  # Use 'table' to get raw data
        elif report_type == "daily":
            report_data = report_generator.generate_daily_report(
                path, None, "table"
            )  # Use 'table' to get raw data
        elif report_type == "weekly":
            report_data = report_generator.generate_weekly_report(
                path, None, "table", False, 0
            )  # Use 'table' to get raw data, Monday start
        elif report_type == "monthly":
            report_data = report_generator.generate_monthly_report(
                path, None, "table"
            )  # Use 'table' to get raw data
        elif report_type == "models":
            report_data = report_generator.generate_models_report(
                path, "all", None, None, "table"
            )  # Use 'table' to get raw data
        elif report_type == "projects":
            report_data = report_generator.generate_projects_report(
                path, "all", None, None, "table"
            )  # Use 'table' to get raw data
        elif report_type == "limits":
            limits_config = config_manager.load_limits_config()
            report_data = report_generator.generate_limits_report(
                path, limits_config, None, export_format or "json"
            )

        if not report_data:
            click.echo("No data to export.", err=True)
            ctx.exit(1)

        # Export the data
        output_path = export_service.export_report_data(
            report_data,
            report_type,
            export_format,
            output,
            config.export.include_metadata,
        )

        # Get export summary
        summary = export_service.get_export_summary(output_path)
        click.echo(f"✅ Export completed successfully!")
        click.echo(f"File: {output_path}")
        click.echo(f"Size: {summary.get('size_human', 'Unknown')}")
        if "rows" in summary:
            click.echo(f"Rows: {summary['rows']}")

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error exporting data: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)
        ctx.exit(1)


@cli.group()
def config():
    """Configuration management commands."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context):
    """Show current configuration."""
    try:
        config = ctx.obj["config"]
        pricing_data = ctx.obj["pricing_data"]

        click.echo("📋 Current Configuration:")
        click.echo()
        click.echo("📁 Paths:")
        click.echo(f"  Messages directory: {config.paths.messages_dir}")
        click.echo(f"  Export directory: {config.paths.export_dir}")
        click.echo()
        click.echo("🎨 UI Settings:")
        click.echo(f"  Table style: {config.ui.table_style}")
        click.echo(f"  Progress bars: {config.ui.progress_bars}")
        click.echo(f"  Colors: {config.ui.colors}")
        click.echo(f"  Live refresh interval: {config.ui.live_refresh_interval}s")
        click.echo()
        click.echo("📤 Export Settings:")
        click.echo(f"  Default format: {config.export.default_format}")
        click.echo(f"  Include metadata: {config.export.include_metadata}")
        click.echo()
        click.echo("🤖 Models:")
        click.echo(f"  Configured models: {len(pricing_data)}")
        for model_name in sorted(pricing_data.keys()):
            click.echo(f"    - {model_name}")

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error showing configuration: {error_msg}", err=True)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str):
    """Set configuration value.

    KEY: Configuration key (e.g., 'paths.messages_dir')
    VALUE: New value to set
    """
    click.echo(f"Configuration setting is not yet implemented.")
    click.echo(f"Would set {key} = {value}")
    click.echo("Please edit the config.toml file directly for now.")


# === Cache management commands ===


@cli.group()
def cache():
    """Cache management commands.

    Manage the DuckDB cache for fast session loading.
    """
    pass


@cache.command("status")
@click.pass_context
def cache_status(ctx: click.Context):
    """Show cache status and statistics."""
    from rich.table import Table

    console = ctx.obj["console"]
    config = ctx.obj["config"]

    try:
        from .cache import CacheManager

        cache_path = config.cache.db_path
        cache_mgr = CacheManager(db_path=cache_path)

        stats = cache_mgr.get_stats()

        console.print("[bold cyan]Cache Status[/bold cyan]")
        console.print()

        # Basic info
        console.print(f"[dim]Database:[/dim] {stats['db_path']}")
        console.print(f"[dim]Enabled:[/dim] {config.cache.enabled}")

        if stats["db_size_bytes"] > 0:
            size_mb = stats["db_size_bytes"] / (1024 * 1024)
            console.print(f"[dim]Size:[/dim] {size_mb:.2f} MB")
        else:
            console.print("[dim]Size:[/dim] Empty (not initialized)")

        console.print()

        # Stats table
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Sessions", f"{stats['sessions']:,}")
        table.add_row("Interactions", f"{stats['interactions']:,}")
        table.add_row("Source files tracked", f"{stats['source_files']:,}")

        console.print(table)

        # Source breakdown
        if stats.get("sources"):
            console.print()
            console.print("[bold]Sessions by source:[/bold]")
            for source, count in stats["sources"].items():
                console.print(f"  {source}: {count:,}")

        # Time range
        if stats.get("time_range") and stats["time_range"]["start"]:
            console.print()
            console.print(f"[dim]Time range:[/dim] {stats['time_range']['start']} to {stats['time_range']['end']}")

        cache_mgr.close()

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error getting cache status: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)


@cache.command("clear")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def cache_clear(ctx: click.Context, yes: bool):
    """Clear all cached data."""
    config = ctx.obj["config"]

    if not yes:
        if not click.confirm("This will delete all cached data. Continue?"):
            click.echo("Cancelled.")
            return

    try:
        from .cache import CacheManager

        cache_path = config.cache.db_path
        cache_mgr = CacheManager(db_path=cache_path)
        cache_mgr.clear()
        cache_mgr.close()

        click.echo("Cache cleared successfully.")

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error clearing cache: {error_msg}", err=True)


@cache.command("rebuild")
@click.option(
    "--hours",
    "-H",
    type=int,
    default=24,
    help="Hours of history to rebuild (default: 24)",
)
@click.option(
    "--source",
    "-s",
    type=click.Choice(["opencode", "claude-code", "codex", "crush", "all", "auto"]),
    default=None,
    help="Data source to rebuild",
)
@click.pass_context
def cache_rebuild(ctx: click.Context, hours: int, source: Optional[str]):
    """Rebuild cache from source data.

    Clears existing cache and reloads data for the specified time range.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn

    config = ctx.obj["config"]
    console = ctx.obj["console"]

    try:
        from .cache import CacheManager
        from .cache.loader import SmartLoader

        # Use provided source or context source
        if source:
            data_source = get_data_source(source)
        else:
            data_source = ctx.obj["data_source"]

        cache_path = config.cache.db_path
        cache_mgr = CacheManager(db_path=cache_path)

        # Clear existing cache
        cache_mgr.clear()
        console.print("[yellow]Cache cleared.[/yellow]")

        # Create loader
        loader = SmartLoader(
            cache_mgr,
            batch_size=config.cache.batch_size,
            fresh_threshold_minutes=config.cache.fresh_threshold_minutes,
        )

        # Progress callback
        last_file = [""]

        def progress_cb(file_path: str, current: int, total: int):
            last_file[0] = Path(file_path).name

        # Rebuild
        with Progress(
            SpinnerColumn(spinner_name=get_spinner_name()),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Loading {hours}h of data...", total=None)

            result = loader.load_with_strategy(
                data_source,
                requested_hours=float(hours),
                progress_callback=progress_cb,
            )

            progress.update(task, completed=True)

        # Show results
        console.print()
        console.print(f"[green]Rebuild complete![/green]")
        console.print(f"  Sessions loaded: {result['immediate_loaded']}")

        if result.get("background_scheduled"):
            console.print(f"  [dim]Background loading scheduled for {len(result.get('gaps_found', []))} gap(s)[/dim]")

        # Show final stats
        stats = cache_mgr.get_stats()
        console.print(f"  Total sessions in cache: {stats['sessions']:,}")
        console.print(f"  Total interactions: {stats['interactions']:,}")

        loader.stop_background()
        cache_mgr.close()

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error rebuilding cache: {error_msg}", err=True)
        if ctx.obj["verbose"]:
            click.echo(f"Details: {str(e)}", err=True)


@cache.command("sync")
@click.pass_context
def cache_sync(ctx: click.Context):
    """Sync cache with source data (incremental update)."""
    from rich.progress import Progress, SpinnerColumn, TextColumn

    config = ctx.obj["config"]
    console = ctx.obj["console"]

    try:
        from .cache import CacheManager
        from .cache.loader import IncrementalLoader

        data_source = ctx.obj["data_source"]
        cache_path = config.cache.db_path
        cache_mgr = CacheManager(db_path=cache_path)
        loader = IncrementalLoader(cache_mgr, batch_size=config.cache.batch_size)

        with Progress(
            SpinnerColumn(spinner_name=get_spinner_name()),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing...", total=None)

            loaded = loader.load_source(data_source)

            progress.update(task, completed=True)

        console.print(f"[green]Sync complete![/green] {loaded} session(s) updated.")

        cache_mgr.close()

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error syncing cache: {error_msg}", err=True)


# === Pricing management commands ===


@cli.group()
def pricing():
    """Pricing management commands.

    Manage model pricing from local config and Models.dev API.
    """
    pass


@pricing.command("status")
@click.pass_context
def pricing_status(ctx: click.Context):
    """Show pricing source status."""
    from rich.table import Table

    console = ctx.obj["console"]
    config = ctx.obj["config"]

    try:
        from .pricing import get_pricing_provider

        provider = get_pricing_provider()
        provider.set_local_pricing(ctx.obj["pricing_data"])
        status = provider.get_status()

        console.print("[bold cyan]Pricing Status[/bold cyan]")
        console.print()
        console.print(f"[dim]Source:[/dim] {status['source']}")
        console.print(f"[dim]Fallback to local:[/dim] {status['fallback_to_local']}")
        console.print(f"[dim]Local models:[/dim] {status['local_models_count']}")

        if status.get("models_dev"):
            md = status["models_dev"]
            console.print()
            console.print("[bold]Models.dev:[/bold]")
            console.print(f"  API URL: {md['api_url']}")
            console.print(f"  Cache TTL: {md['cache_ttl_hours']}h")
            console.print(f"  File cache: {'exists' if md['file_cache_exists'] else 'not found'}")

            if md.get("file_cache_age"):
                age_hours = md["file_cache_age"] / 3600
                console.print(f"  Cache age: {age_hours:.1f}h")

            console.print(f"  Models cached: {md['models_count']}")

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error getting pricing status: {error_msg}", err=True)


@pricing.command("update")
@click.pass_context
def pricing_update(ctx: click.Context):
    """Refresh pricing from Models.dev API."""
    console = ctx.obj["console"]

    try:
        from .pricing import get_pricing_provider

        provider = get_pricing_provider()

        console.print("Fetching pricing from Models.dev...")

        if provider.refresh_models_dev():
            status = provider.get_status()
            models_count = status.get("models_dev", {}).get("models_count", 0)
            console.print(f"[green]Success![/green] {models_count} models updated.")
        else:
            console.print("[yellow]Warning:[/yellow] Could not fetch from Models.dev")
            console.print("[dim]Ensure 'requests' package is installed and network is available.[/dim]")

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error updating pricing: {error_msg}", err=True)


@pricing.command("list")
@click.option("--source", "-s", type=click.Choice(["local", "models.dev", "all"]), default="all")
@click.pass_context
def pricing_list(ctx: click.Context, source: str):
    """List available model pricing."""
    from rich.table import Table

    console = ctx.obj["console"]

    try:
        from .pricing import get_pricing_provider

        provider = get_pricing_provider()
        provider.set_local_pricing(ctx.obj["pricing_data"])

        # Get pricing based on source filter
        if source == "local":
            pricing = {
                k: provider._convert_local_pricing(v)
                for k, v in (provider._local_pricing or {}).items()
            }
        elif source == "models.dev":
            client = provider.get_models_dev_client()
            pricing = client.fetch_pricing()
        else:
            pricing = provider.get_all_pricing()

        if not pricing:
            console.print("[dim]No pricing data available.[/dim]")
            return

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Model", style="cyan")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cache R", justify="right")
        table.add_column("Cache W", justify="right")
        table.add_column("Context", justify="right")

        for model_id in sorted(pricing.keys())[:50]:  # Limit to 50
            p = pricing[model_id]
            table.add_row(
                model_id[:40],
                f"${p.input:.2f}",
                f"${p.output:.2f}",
                f"${p.cache_read:.2f}",
                f"${p.cache_write:.2f}",
                f"{p.context_window:,}",
            )

        console.print(table)

        if len(pricing) > 50:
            console.print(f"[dim]...and {len(pricing) - 50} more models[/dim]")

    except Exception as e:
        error_msg = create_user_friendly_error(e)
        click.echo(f"Error listing pricing: {error_msg}", err=True)


def main():
    """Entry point for the CLI application."""
    cli()
