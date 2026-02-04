"""Live monitoring service for OpenCode Monitor."""

import sys
import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, Any, List
from rich.live import Live
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.tree import Tree

# Platform-specific keyboard input with threading
from queue import Queue, Empty

_key_queue: Queue = Queue()
_keyboard_thread_started = False


def _start_keyboard_listener():
    """Start background thread for keyboard input."""
    global _keyboard_thread_started
    if _keyboard_thread_started:
        return
    _keyboard_thread_started = True

    def listen():
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        # Handle special keys (arrows, etc.)
                        if key in (b"\x00", b"\xe0"):
                            special = msvcrt.getch()
                            # Arrow keys: H=up, P=down, K=left, M=right
                            if special == b"H":
                                _key_queue.put("k")  # up -> k
                            elif special == b"P":
                                _key_queue.put("j")  # down -> j
                        else:
                            _key_queue.put(key.decode("utf-8", errors="ignore").lower())
                    time.sleep(0.05)
                except Exception:
                    break
        else:
            import select
            import tty
            import termios

            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                while True:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        key = sys.stdin.read(1)
                        _key_queue.put(key.lower())
            except Exception:
                pass
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()


def get_key() -> Optional[str]:
    """Get a keypress from queue (non-blocking)."""
    try:
        return _key_queue.get_nowait()
    except Empty:
        return None


from ..models.session import SessionData, InteractionFile, TokenUsage
from ..models.limits import LimitsConfig, ProviderLimit
from ..utils.file_utils import FileProcessor
from ..ui.dashboard import DashboardUI
from ..config import ModelPricing

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..utils.data_source import DataSource


class LiveMonitor:
    """Service for live monitoring of AI coding sessions."""

    def __init__(
        self,
        pricing_data: Dict[str, ModelPricing],
        console: Optional[Console] = None,
        session_max_hours: float = 5.0,
        limits_config: Optional[LimitsConfig] = None,
        data_source: Optional["DataSource"] = None,
    ):
        """Initialize live monitor.

        Args:
            pricing_data: Model pricing information
            console: Rich console for output
            session_max_hours: Maximum session duration for progress bar (hours)
            limits_config: Subscription limits configuration
            data_source: Data source for loading sessions (optional, defaults to OpenCode)
        """
        self.pricing_data = pricing_data
        self.console = console or Console()
        self.dashboard_ui = DashboardUI(console)
        self.session_max_hours = session_max_hours
        self.limits_config = limits_config
        self._data_source = data_source

        # Cache for daily cost calculation (expensive, update every N ticks)
        self._daily_cost_cache: Optional[Decimal] = None
        self._daily_cost_update_tick = 0
        self._current_base_path: Optional[str] = None
        self._tick_count = 0

        # Session cache with mtime tracking to reduce I/O
        self._session_cache: Dict[str, SessionData] = {}  # session_path -> SessionData
        self._session_mtime: Dict[str, float] = {}  # session_path -> last mtime
        self._last_dir_scan_tick = 0  # Last tick when we scanned directories

        # UI state for keybindings
        self._view_mode = "grid"  # "grid" or "list"
        self._show_provider_details = False
        self._force_refresh = False
        self._should_quit = False
        self._paused = False
        self._refresh_interval = 10  # Current interval (can be changed with +/-)
        self._selected_project_idx = 0  # For navigation
        self._selected_provider_filter: Optional[str] = None  # Filter by provider
        self._show_help = False  # Toggle help overlay
        self._available_providers: List[str] = []  # For filter cycling

    def _find_sessions(self, base_path: str) -> List[Path]:
        """Find session paths using data source or FileProcessor."""
        if self._data_source:
            return self._data_source.find_sessions(base_path)
        return self._find_sessions(base_path)

    def _load_session(self, session_path: Path) -> Optional[SessionData]:
        """Load a session using data source or FileProcessor."""
        if self._data_source:
            return self._data_source.load_session(session_path)
        return self._load_session(session_path)

    def _load_all_sessions(
        self, base_path: Optional[str] = None, limit: Optional[int] = None
    ) -> List[SessionData]:
        """Load all sessions using data source or FileProcessor."""
        if self._data_source:
            return self._data_source.load_all_sessions(base_path, limit)
        if base_path:
            return FileProcessor.load_all_sessions(base_path, limit)
        return []

    def _get_most_recent_session(self, base_path: str) -> Optional[SessionData]:
        """Get most recent session using data source or FileProcessor."""
        if self._data_source:
            sessions = self._data_source.load_all_sessions(base_path, limit=1)
            return sessions[0] if sessions else None
        return self._get_most_recent_session(base_path)

    def _handle_keypress(self) -> bool:
        """Handle keyboard input. Returns True if should continue, False to quit."""
        key = get_key()
        if key is None:
            return True

        # Q - Quit
        if key == "q":
            self._should_quit = True
            return False

        # R - Force refresh
        elif key == "r":
            self._force_refresh = True

        # V - Toggle view mode (grid/list)
        elif key == "v":
            self._view_mode = "list" if self._view_mode == "grid" else "grid"

        # P - Toggle provider details
        elif key == "p":
            self._show_provider_details = not self._show_provider_details

        # Space or P - Pause/Resume
        elif key == " ":
            self._paused = not self._paused

        # + or = - Increase refresh interval
        elif key in ("+", "="):
            self._refresh_interval = min(60, self._refresh_interval + 5)

        # - - Decrease refresh interval
        elif key == "-":
            self._refresh_interval = max(2, self._refresh_interval - 5)

        # Arrow keys / j/k - Navigate projects
        elif key == "j":  # Down
            self._selected_project_idx += 1
        elif key == "k":  # Up
            self._selected_project_idx = max(0, self._selected_project_idx - 1)

        # F - Cycle provider filter
        elif key == "f":
            if self._available_providers:
                if self._selected_provider_filter is None:
                    self._selected_provider_filter = self._available_providers[0]
                else:
                    try:
                        idx = self._available_providers.index(
                            self._selected_provider_filter
                        )
                        idx = (idx + 1) % (len(self._available_providers) + 1)
                        if idx == len(self._available_providers):
                            self._selected_provider_filter = None
                        else:
                            self._selected_provider_filter = self._available_providers[
                                idx
                            ]
                    except ValueError:
                        self._selected_provider_filter = None

        # H or ? - Toggle help
        elif key in ("h", "?"):
            self._show_help = not self._show_help

        # Tab - Focus switch (placeholder for future)
        elif key == "\t":
            pass  # TODO: implement focus switching

        return True

    def _get_keybindings_help(self) -> str:
        """Return keybindings help text."""
        status = (
            "[yellow]PAUSED[/yellow]"
            if self._paused
            else f"[green]{self._refresh_interval}s[/green]"
        )
        filter_text = (
            f"[cyan]{self._selected_provider_filter}[/cyan]"
            if self._selected_provider_filter
            else "[dim]all[/dim]"
        )
        return (
            f"[dim]Q[/dim] Quit  "
            f"[dim]R[/dim] Refresh  "
            f"[dim]V[/dim] View:{self._view_mode}  "
            f"[dim]P[/dim] Details  "
            f"[dim]Space[/dim] {status}  "
            f"[dim]+/-[/dim] Interval  "
            f"[dim]F[/dim] Filter:{filter_text}  "
            f"[dim]J/K[/dim] Nav  "
            f"[dim]?[/dim] Help"
        )

    def start_monitoring(
        self,
        base_path: str,
        refresh_interval: int = 10,
        project_filter: Optional[str] = None,
    ):
        """Start live monitoring of the most recent session.

        Args:
            base_path: Path to directory containing sessions
            refresh_interval: Update interval in seconds
            project_filter: Filter by project name (partial match) to prevent jumping.
                           Use "*" for aggregate view across all projects.
        """
        try:
            # Store base_path for daily cost calculation
            self._current_base_path = base_path
            self._tick_count = 0
            self._daily_cost_cache = None

            # Special case: aggregate mode for all projects
            # Use "all" or "*" to show aggregate stats
            if project_filter in ("*", "all", "ALL"):
                self._start_aggregate_monitoring(base_path, refresh_interval)
                return

            # Find the most recent session (with optional project filter)
            recent_session = self._get_filtered_session(base_path, project_filter)
            if not recent_session:
                if project_filter:
                    self.console.print(
                        f"[red]No sessions found for project '{project_filter}' in {base_path}[/red]"
                    )
                else:
                    self.console.print(f"[red]No sessions found in {base_path}[/red]")
                return

            project_info = (
                f" [dim](project: {project_filter})[/dim]" if project_filter else ""
            )
            self.console.print(
                f"[green]Starting live monitoring of session: {recent_session.session_id}[/green]{project_info}"
            )
            self.console.print(
                f"[cyan]Update interval: {refresh_interval} seconds[/cyan]"
            )
            # Initialize keybinding state
            self._refresh_interval = refresh_interval
            self._should_quit = False
            self._paused = False

            # Start keyboard listener thread
            _start_keyboard_listener()

            # Start live monitoring
            with Live(
                self._generate_dashboard(recent_session),
                refresh_per_second=4,
                console=self.console,
                transient=False,  # Keep output visible
            ) as live:
                last_update = 0.0
                while not self._should_quit:
                    # Handle keyboard input
                    if not self._handle_keypress():
                        break

                    # Update display if not paused and interval elapsed (or force refresh)
                    current_time = time.time()
                    if self._force_refresh or (
                        not self._paused
                        and current_time - last_update >= self._refresh_interval
                    ):
                        # Check for most recent session (with project filter to prevent jumping)
                        most_recent = self._get_filtered_session(
                            base_path, project_filter
                        )

                        if most_recent:
                            # If we detected a different session, switch to it
                            if most_recent.session_id != recent_session.session_id:
                                recent_session = most_recent
                            else:
                                # Same session, just reload its data
                                updated_session = self._load_session(
                                    recent_session.session_path
                                )
                                if updated_session:
                                    recent_session = updated_session

                        # Update dashboard
                        self._tick_count += 1
                        live.update(self._generate_dashboard(recent_session))
                        last_update = current_time
                        self._force_refresh = False

                    # Small sleep to prevent CPU spinning
                    time.sleep(0.1)

        except KeyboardInterrupt:
            pass  # Clean exit

    def _start_aggregate_monitoring(self, base_path: str, refresh_interval: int = 10):
        """Start aggregate monitoring across all projects.

        Shows combined statistics from all recent sessions.
        """
        self._refresh_interval = refresh_interval
        self._should_quit = False
        self._paused = False

        # Start keyboard listener thread
        _start_keyboard_listener()

        with Live(
            self._generate_aggregate_dashboard(base_path),
            refresh_per_second=4,
            console=self.console,
            screen=True,  # Use alternate screen buffer (no flicker)
        ) as live:
            last_update = 0.0
            while not self._should_quit:
                # Handle keyboard input
                if not self._handle_keypress():
                    break

                # Update display if not paused and interval elapsed (or force refresh)
                current_time = time.time()
                if self._force_refresh or (
                    not self._paused
                    and current_time - last_update >= self._refresh_interval
                ):
                    live.update(self._generate_aggregate_dashboard(base_path))
                    last_update = current_time
                    self._force_refresh = False

                # Small sleep to prevent CPU spinning
                time.sleep(0.1)

    def _generate_aggregate_dashboard(self, base_path: str) -> Layout:
        """Generate aggregate dashboard with Control Tower design.

        Shows:
        - Header with global vitals
        - Provider limits section with progress bars
        - Project cards grid
        - Live activity stream

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Rich layout for aggregate dashboard
        """
        today = datetime.now().date()
        now = datetime.now()
        session_dirs = self._find_sessions(base_path)

        # Aggregate stats by project AND by provider
        project_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "sessions": 0,
                "interactions": 0,
                "tokens": TokenUsage(),
                "cost": Decimal("0.0"),
                "latest_time": None,
                "latest_model": None,
                "cache_rate": 0.0,
            }
        )

        # Provider usage tracking (for limits display)
        provider_usage: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "requests": 0,
                "tokens": 0,
                "cost": Decimal("0.0"),
            }
        )

        # Hierarchical usage tracking: provider -> model -> agent -> category
        # Structure: {provider: {model: {agent: {category: {"requests": N, "cost": D}}}}}
        usage_hierarchy: Dict[str, Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]] = (
            defaultdict(
                lambda: defaultdict(
                    lambda: defaultdict(
                        lambda: defaultdict(
                            lambda: {"requests": 0, "cost": Decimal("0.0")}
                        )
                    )
                )
            )
        )

        total_tokens = TokenUsage()
        total_cost = Decimal("0.0")
        total_sessions = 0
        total_interactions = 0
        recent_files: List[tuple] = []

        for session_dir in session_dirs:
            session = self._load_session(session_dir)
            if not session or not session.files:
                continue

            # Filter to today's files only
            today_files = [
                f
                for f in session.files
                if f.modification_time and f.modification_time.date() == today
            ]

            if not today_files:
                continue

            project_name = session.project_name
            stats = project_stats[project_name]

            stats["sessions"] += 1
            stats["interactions"] += len(today_files)
            total_sessions += 1
            total_interactions += len(today_files)

            for file in today_files:
                # Aggregate tokens
                stats["tokens"].input += file.tokens.input
                stats["tokens"].output += file.tokens.output
                stats["tokens"].cache_write += file.tokens.cache_write
                stats["tokens"].cache_read += file.tokens.cache_read

                total_tokens.input += file.tokens.input
                total_tokens.output += file.tokens.output
                total_tokens.cache_write += file.tokens.cache_write
                total_tokens.cache_read += file.tokens.cache_read

                # Calculate cost
                file_cost = file.calculate_cost(self.pricing_data)
                stats["cost"] += file_cost
                total_cost += file_cost

                # Track provider usage (extract provider from model_id)
                provider_id = (
                    file.model_id.split("/")[0] if "/" in file.model_id else "unknown"
                )
                provider_usage[provider_id]["requests"] += 1
                provider_usage[provider_id]["tokens"] += file.tokens.total
                provider_usage[provider_id]["cost"] += file_cost

                # Track hierarchical usage: provider -> model -> agent -> category
                # Use file.provider_id if available, otherwise parse from model_id
                hierarchy_provider = file.provider_id or provider_id
                model_name = (
                    file.model_id.split("/")[-1]
                    if "/" in file.model_id
                    else file.model_id
                )
                agent_name = file.agent or "unknown"
                category_name = file.category or "unknown"
                usage_hierarchy[hierarchy_provider][model_name][agent_name][
                    category_name
                ]["requests"] += 1
                usage_hierarchy[hierarchy_provider][model_name][agent_name][
                    category_name
                ]["cost"] += file_cost

                # Track latest activity
                if (
                    stats["latest_time"] is None
                    or file.modification_time > stats["latest_time"]
                ):
                    stats["latest_time"] = file.modification_time
                    stats["latest_model"] = (
                        file.model_id.split("/")[-1]
                        if "/" in file.model_id
                        else file.model_id
                    )

                recent_files.append((project_name, file, session))

            # Calculate cache rate
            total_input = stats["tokens"].input + stats["tokens"].cache_read
            if total_input > 0:
                stats["cache_rate"] = (stats["tokens"].cache_read / total_input) * 100

        recent_files.sort(key=lambda x: x[1].modification_time, reverse=True)

        # ═══════════════════════════════════════════════════════════════════════
        # BUILD LAYOUT - "Control Tower" Design
        # ═══════════════════════════════════════════════════════════════════════

        layout = Layout()
        current_time = now.strftime("%H:%M:%S")

        # Determine overall status
        status = "[green]NOMINAL[/green]"
        if self.limits_config:
            for provider in self.limits_config.providers:
                usage = provider_usage.get(provider.provider_id, {})
                if provider.monthly_cost_limit:
                    pct = (
                        float(usage.get("cost", 0))
                        / float(provider.monthly_cost_limit)
                        * 100
                    )
                    if pct > 90:
                        status = "[red]CRITICAL[/red]"
                        break
                    elif pct > 75:
                        status = "[yellow]WARNING[/yellow]"

        # ─────────────────────────────────────────────────────────────────────
        # HEADER - Global Vitals
        # ─────────────────────────────────────────────────────────────────────
        header_text = (
            f"[bold cyan]OCMONITOR AGGREGATE[/bold cyan]  "
            f"[dim]|[/dim]  [bold white]${total_cost:.2f}[/bold white] [dim]cost[/dim]  "
            f"[dim]|[/dim]  [bold white]{total_sessions}[/bold white] [dim]sessions[/dim]  "
            f"[dim]|[/dim]  [bold white]{total_interactions:,}[/bold white] [dim]interactions[/dim]  "
            f"[dim]|[/dim]  {status}  "
            f"[dim]|[/dim]  [dim]{current_time}[/dim]"
        )
        header = Panel(header_text, border_style="cyan", padding=(0, 1))

        # ─────────────────────────────────────────────────────────────────────
        # PROVIDER LIMITS SECTION
        # ─────────────────────────────────────────────────────────────────────
        provider_cards = []

        if self.limits_config and self.limits_config.providers:
            for provider in self.limits_config.providers[:4]:  # Max 4 providers
                usage = provider_usage.get(
                    provider.provider_id,
                    {"requests": 0, "tokens": 0, "cost": Decimal("0.0")},
                )
                card_text = self._create_provider_card(provider, usage)
                provider_cards.append(
                    Panel(
                        card_text,
                        title=provider.display_name or provider.provider_id,
                        border_style="dim",
                    )
                )
        else:
            # No limits configured - show basic provider stats
            for provider_id, usage in sorted(
                provider_usage.items(), key=lambda x: x[1]["cost"], reverse=True
            )[:4]:
                card_text = (
                    f"[dim]Requests:[/dim] [white]{usage['requests']:,}[/white]\n"
                    f"[dim]Tokens:[/dim] [white]{usage['tokens']:,}[/white]\n"
                    f"[dim]Cost:[/dim] [green]${usage['cost']:.2f}[/green]"
                )
                provider_cards.append(
                    Panel(card_text, title=provider_id, border_style="dim")
                )

        if provider_cards:
            providers_panel = Panel(
                Columns(provider_cards, equal=True, expand=True),
                title="[bold]Provider Limits[/bold]",
                border_style="blue",
            )
        else:
            providers_panel = Panel(
                "[dim]No provider data[/dim]",
                title="Provider Limits",
                border_style="dim",
            )

        # ─────────────────────────────────────────────────────────────────────
        # PROJECT CARDS SECTION
        # ─────────────────────────────────────────────────────────────────────
        project_cards = []
        sorted_projects = sorted(
            project_stats.items(), key=lambda x: x[1]["cost"], reverse=True
        )

        for project_name, stats in sorted_projects[:6]:  # Max 6 projects
            # Status indicator based on last activity
            if stats["latest_time"]:
                delta = now - stats["latest_time"]
                if delta.total_seconds() < 60:
                    status_icon = "[green]●[/green]"
                    time_ago = f"{int(delta.total_seconds())}s"
                elif delta.total_seconds() < 600:
                    status_icon = "[yellow]●[/yellow]"
                    time_ago = f"{int(delta.total_seconds() / 60)}m"
                else:
                    status_icon = "[red]●[/red]"
                    time_ago = f"{int(delta.total_seconds() / 60)}m"
            else:
                status_icon = "[dim]○[/dim]"
                time_ago = "--"

            # Truncate project name
            display_name = (
                project_name[:18] + ".." if len(project_name) > 20 else project_name
            )

            card_lines = [
                f"{status_icon} [dim]{time_ago} ago[/dim]",
                f"[dim]Sessions:[/dim] {stats['sessions']}  [dim]Req:[/dim] {stats['interactions']}",
                f"[dim]Model:[/dim] [cyan]{(stats['latest_model'] or '--')[:15]}[/cyan]",
                f"[green]${stats['cost']:.2f}[/green]  [dim]{stats['tokens'].total / 1_000_000:.1f}M tok[/dim]",
            ]

            if stats["cache_rate"] > 0:
                card_lines.append(
                    f"[dim]Cache:[/dim] [cyan]{stats['cache_rate']:.0f}%[/cyan]"
                )

            project_cards.append(
                Panel(
                    "\n".join(card_lines), title=display_name, border_style="dim cyan"
                )
            )

        if project_cards:
            projects_panel = Panel(
                Columns(project_cards, equal=True, expand=True),
                title="[bold]Active Projects[/bold]",
                border_style="cyan",
            )
        else:
            projects_panel = Panel(
                "[dim]No active projects today[/dim]",
                title="Active Projects",
                border_style="dim",
            )

        # ─────────────────────────────────────────────────────────────────────
        # LIVE STREAM SECTION
        # ─────────────────────────────────────────────────────────────────────
        stream_lines = []
        for project_name, file, session in recent_files[:4]:
            time_ago = now - file.modification_time
            if time_ago.total_seconds() < 60:
                time_str = f"{int(time_ago.total_seconds()):>3}s"
            else:
                time_str = f"{int(time_ago.total_seconds() / 60):>3}m"

            short_project = (
                project_name[:12] + ".." if len(project_name) > 14 else project_name
            )
            model_short = (
                file.model_id.split("/")[-1][:12]
                if "/" in file.model_id
                else file.model_id[:12]
            )

            stream_lines.append(
                f"[dim]{time_str}[/dim] [cyan]{short_project:<14}[/cyan] "
                f"[white]{file.tokens.total:>8,}[/white] [dim]tok[/dim]  "
                f"[dim]({model_short})[/dim]"
            )

        stream_text = (
            "\n".join(stream_lines) if stream_lines else "[dim]No recent activity[/dim]"
        )
        stream_panel = Panel(stream_text, title="Live Stream", border_style="dim")

        # ─────────────────────────────────────────────────────────────────────
        # USAGE BREAKDOWN TREE (full hierarchy: provider -> model -> agent -> category)
        # ─────────────────────────────────────────────────────────────────────
        usage_tree = Tree("[bold]Usage Breakdown[/bold]")

        if not usage_hierarchy:
            usage_tree.add("[dim]No data[/dim]")
        else:
            # Calculate totals for sorting
            def calc_provider_totals(provider_data: dict) -> tuple:
                total_cost = Decimal("0.0")
                total_reqs = 0
                for model_data in provider_data.values():
                    for agent_data in model_data.values():
                        for cat_stats in agent_data.values():
                            total_cost += cat_stats["cost"]
                            total_reqs += cat_stats["requests"]
                return total_cost, total_reqs

            def calc_model_totals(model_data: dict) -> tuple:
                total_cost = Decimal("0.0")
                total_reqs = 0
                for agent_data in model_data.values():
                    for cat_stats in agent_data.values():
                        total_cost += cat_stats["cost"]
                        total_reqs += cat_stats["requests"]
                return total_cost, total_reqs

            def calc_agent_totals(agent_data: dict) -> tuple:
                total_cost = Decimal("0.0")
                total_reqs = 0
                for cat_stats in agent_data.values():
                    total_cost += cat_stats["cost"]
                    total_reqs += cat_stats["requests"]
                return total_cost, total_reqs

            # Sort providers by cost
            sorted_providers = sorted(
                usage_hierarchy.items(),
                key=lambda x: calc_provider_totals(x[1])[0],
                reverse=True,
            )

            for provider_id, models_data in sorted_providers[:3]:
                p_cost, p_reqs = calc_provider_totals(models_data)
                provider_branch = usage_tree.add(
                    f"[cyan]{provider_id}[/cyan] [dim]({p_reqs} req, [green]${p_cost:.2f}[/green])[/dim]"
                )

                # Sort models by cost
                sorted_models = sorted(
                    models_data.items(),
                    key=lambda x: calc_model_totals(x[1])[0],
                    reverse=True,
                )

                for model_name, agents_data in sorted_models[:2]:
                    m_cost, m_reqs = calc_model_totals(agents_data)
                    model_branch = provider_branch.add(
                        f"[white]{model_name[:20]}[/white] [dim]({m_reqs} req, [green]${m_cost:.2f}[/green])[/dim]"
                    )

                    # Sort agents by requests
                    sorted_agents = sorted(
                        agents_data.items(),
                        key=lambda x: calc_agent_totals(x[1])[1],
                        reverse=True,
                    )

                    for agent_name, categories_data in sorted_agents[:3]:
                        a_cost, a_reqs = calc_agent_totals(categories_data)
                        agent_branch = model_branch.add(
                            f"[magenta]{agent_name}[/magenta] [dim]({a_reqs} req)[/dim]"
                        )

                        # Sort categories by requests
                        sorted_categories = sorted(
                            categories_data.items(),
                            key=lambda x: x[1]["requests"],
                            reverse=True,
                        )

                        for cat_name, cat_stats in sorted_categories[:4]:
                            agent_branch.add(
                                f"[yellow]{cat_name}[/yellow]: {cat_stats['requests']} req"
                            )

        breakdown_panel = Panel(
            usage_tree, title="Breakdown", border_style="dim magenta"
        )

        # ─────────────────────────────────────────────────────────────────────
        # FOOTER - Keybindings help
        # ─────────────────────────────────────────────────────────────────────
        footer_text = self._get_keybindings_help()
        footer = Panel(footer_text, border_style="dim", padding=(0, 1))

        # ─────────────────────────────────────────────────────────────────────
        # ASSEMBLE LAYOUT
        # ─────────────────────────────────────────────────────────────────────
        layout.split_column(
            Layout(header, size=3),
            Layout(providers_panel, size=7),
            Layout(name="middle", ratio=1),
            Layout(stream_panel, size=6),
            Layout(footer, size=3),
        )

        # Middle section: Projects + Breakdown side by side
        layout["middle"].split_row(
            Layout(projects_panel, ratio=2),
            Layout(breakdown_panel, ratio=1),
        )

        return layout

    def _create_provider_card(
        self, provider: ProviderLimit, usage: Dict[str, Any]
    ) -> str:
        """Create a provider card with progress bar.

        Args:
            provider: Provider limit configuration
            usage: Current usage stats

        Returns:
            Formatted card text
        """
        lines = []

        # Determine limit type and calculate percentage
        if provider.monthly_cost_limit:
            # Cost-based limit
            limit_val = float(provider.monthly_cost_limit)
            current_val = float(usage.get("cost", 0))
            pct = min(100, (current_val / limit_val) * 100) if limit_val > 0 else 0
            lines.append(f"[dim]Cost Cap[/dim] ${current_val:.0f}/${limit_val:.0f}")
        elif provider.effective_requests_per_window:
            # Request-based limit
            limit_val = provider.effective_requests_per_window
            current_val = usage.get("requests", 0)
            pct = min(100, (current_val / limit_val) * 100) if limit_val > 0 else 0
            lines.append(
                f"[dim]{provider.window_hours}h Window[/dim] {current_val}/{limit_val} req"
            )
        else:
            # No specific limit
            lines.append(f"[dim]Requests:[/dim] {usage.get('requests', 0):,}")
            lines.append(f"[dim]Cost:[/dim] ${usage.get('cost', 0):.2f}")
            return "\n".join(lines)

        # Create progress bar
        bar_width = 16
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Color based on percentage
        if pct >= 90:
            color = "red"
            status = "CRIT"
        elif pct >= 75:
            color = "yellow"
            status = "WARN"
        else:
            color = "green"
            status = "OK"

        lines.append(f"[{color}]{bar}[/{color}] {pct:.0f}%")
        lines.append(f"[{color}]{status}[/{color}]")

        return "\n".join(lines)

    def _get_filtered_session(
        self, base_path: str, project_filter: Optional[str] = None
    ) -> Optional[SessionData]:
        """Get the most recent session, optionally filtered by project.

        Uses mtime caching to reduce I/O:
        - Directory scan only every 6 ticks (~30s with 5s interval)
        - Session reload only if mtime changed

        Args:
            base_path: Path to directory containing sessions
            project_filter: Filter by project name (partial, case-insensitive)

        Returns:
            Most recent session matching filter, or None
        """
        # Determine if we need a full directory scan
        # Scan every 6 ticks (~30 seconds) or on first call
        needs_dir_scan = (
            self._tick_count == 0
            or self._tick_count - self._last_dir_scan_tick >= 6
            or not self._session_cache
        )

        if needs_dir_scan:
            self._last_dir_scan_tick = self._tick_count
            session_dirs = self._find_sessions(base_path)
        else:
            # Use cached session paths
            session_dirs = [Path(p) for p in self._session_cache.keys()]

        if not session_dirs:
            return None

        project_lower = project_filter.lower() if project_filter else None
        matching_session: Optional[SessionData] = None
        latest_time: Optional[datetime] = None

        for session_dir in session_dirs:
            session_path = str(session_dir)

            # Check mtime to decide if reload is needed
            session = self._get_cached_session(session_path)
            if not session:
                continue

            # If no project filter, just find the most recent
            if not project_lower:
                if session.files:
                    session_latest = max(f.modification_time for f in session.files)
                    if latest_time is None or session_latest > latest_time:
                        latest_time = session_latest
                        matching_session = session
                continue

            # Check if project matches (partial, case-insensitive)
            matches = False
            if project_lower in session.project_name.lower():
                matches = True
            else:
                # Also check file paths
                for file in session.files:
                    if file.project_path and project_lower in file.project_path.lower():
                        matches = True
                        break

            if matches:
                # Find the latest file time in this session
                if session.files:
                    session_latest = max(f.modification_time for f in session.files)
                    if latest_time is None or session_latest > latest_time:
                        latest_time = session_latest
                        matching_session = session

        return matching_session

    def _get_cached_session(self, session_path: str) -> Optional[SessionData]:
        """Get session from cache, reloading only if mtime changed.

        Args:
            session_path: Path to session directory

        Returns:
            SessionData or None if loading failed
        """
        try:
            # Get current mtime of session directory
            path_obj = Path(session_path)
            if not path_obj.exists():
                # Session was deleted, remove from cache
                self._session_cache.pop(session_path, None)
                self._session_mtime.pop(session_path, None)
                return None

            # Check mtime of the directory and its most recent file
            current_mtime = path_obj.stat().st_mtime

            # Also check mtime of JSON files in the directory
            json_files = list(path_obj.glob("*.json"))
            if json_files:
                latest_file_mtime = max(f.stat().st_mtime for f in json_files)
                current_mtime = max(current_mtime, latest_file_mtime)

            cached_mtime = self._session_mtime.get(session_path)

            # If mtime unchanged and we have cached data, return cache
            if cached_mtime is not None and cached_mtime >= current_mtime:
                cached_session = self._session_cache.get(session_path)
                if cached_session:
                    return cached_session

            # Reload session
            session = self._load_session(path_obj)
            if session:
                self._session_cache[session_path] = session
                self._session_mtime[session_path] = current_mtime

            return session

        except (OSError, IOError):
            # File system error, try to return cached version
            return self._session_cache.get(session_path)

    def _generate_dashboard(self, session: SessionData):
        """Generate dashboard layout for the session.

        Args:
            session: Session to monitor

        Returns:
            Rich layout for the dashboard
        """
        # Get the most recent file
        recent_file = None
        if session.files:
            recent_file = max(session.files, key=lambda f: f.modification_time)

        # Calculate burn rate
        burn_rate = self._calculate_burn_rate(session)

        # Get model pricing for quota and context window
        quota = None
        context_window = 200000  # Default

        if recent_file and recent_file.model_id in self.pricing_data:
            model_pricing = self.pricing_data[recent_file.model_id]
            quota = model_pricing.session_quota
            context_window = model_pricing.context_window

        # Calculate daily cost (cached, updated every 12 ticks ~ 1 minute)
        daily_cost = self._get_cached_daily_cost()

        return self.dashboard_ui.create_dashboard_layout(
            session=session,
            recent_file=recent_file,
            pricing_data=self.pricing_data,
            burn_rate=burn_rate,
            quota=quota,
            context_window=context_window,
            daily_cost=daily_cost,
            session_max_hours=self.session_max_hours,
        )

    def _calculate_burn_rate(self, session: SessionData) -> float:
        """Calculate token burn rate for a session (total tokens / total session time).

        Args:
            session: SessionData object

        Returns:
            Tokens per minute for the entire session
        """
        # Get total tokens for the session
        total_tokens = session.total_tokens.total

        # If no tokens, return 0
        if total_tokens == 0:
            return 0.0

        # Calculate session duration from start time to now
        if session.start_time:
            current_time = datetime.now()
            session_duration = current_time - session.start_time
            duration_minutes = session_duration.total_seconds() / 60

            if duration_minutes > 0:
                return total_tokens / duration_minutes

        return 0.0

    def _get_cached_daily_cost(self) -> Optional[Decimal]:
        """Get daily cost with caching (recalculate every 12 ticks ~ 1 minute).

        Returns:
            Today's total cost across all sessions, or None if unavailable
        """
        # Update cache every 12 ticks (about 1 minute with 5s interval)
        if (
            self._daily_cost_cache is None
            or self._tick_count - self._daily_cost_update_tick >= 12
        ):
            self._daily_cost_cache = self._calculate_daily_cost()
            self._daily_cost_update_tick = self._tick_count

        return self._daily_cost_cache

    def _calculate_daily_cost(self) -> Optional[Decimal]:
        """Calculate today's total cost across all sessions.

        Returns:
            Today's total cost, or None if base_path not available
        """
        if not self._current_base_path:
            return None

        today = datetime.now().date()
        session_dirs = self._find_sessions(self._current_base_path)
        total_cost = Decimal("0.0")

        for session_dir in session_dirs:
            session = self._load_session(session_dir)
            if not session or not session.files:
                continue

            # Sum cost of today's files only
            for file in session.files:
                if file.modification_time and file.modification_time.date() == today:
                    total_cost += file.calculate_cost(self.pricing_data)

        return total_cost

    def get_session_status(self, base_path: str) -> Dict[str, Any]:
        """Get current status of the most recent session.

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Dictionary with session status information
        """
        recent_session = self._get_most_recent_session(base_path)
        if not recent_session:
            return {"status": "no_sessions", "message": "No sessions found"}

        recent_file = None
        if recent_session.files:
            recent_file = max(recent_session.files, key=lambda f: f.modification_time)

        # Calculate how long ago the last activity was
        last_activity = None
        if recent_file:
            last_activity = time.time() - recent_file.modification_time.timestamp()

        # Determine activity status
        activity_status = "unknown"
        if last_activity is not None:
            if last_activity < 60:  # Less than 1 minute
                activity_status = "active"
            elif last_activity < 300:  # Less than 5 minutes
                activity_status = "recent"
            elif last_activity < 1800:  # Less than 30 minutes
                activity_status = "idle"
            else:
                activity_status = "inactive"

        return {
            "status": "found",
            "session_id": recent_session.session_id,
            "interaction_count": recent_session.interaction_count,
            "total_tokens": recent_session.total_tokens.total,
            "total_cost": float(recent_session.calculate_total_cost(self.pricing_data)),
            "models_used": recent_session.models_used,
            "last_activity_seconds": last_activity,
            "activity_status": activity_status,
            "burn_rate": self._calculate_burn_rate(recent_session),
            "recent_file": {
                "name": recent_file.file_name,
                "model": recent_file.model_id,
                "tokens": recent_file.tokens.total,
            }
            if recent_file
            else None,
        }

    def monitor_single_update(self, base_path: str) -> Optional[Dict[str, Any]]:
        """Get a single update of the monitoring data.

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Monitoring data or None if no session found
        """
        recent_session = self._get_most_recent_session(base_path)
        if not recent_session:
            return None

        recent_file = None
        if recent_session.files:
            recent_file = max(recent_session.files, key=lambda f: f.modification_time)

        return {
            "timestamp": time.time(),
            "session": {
                "id": recent_session.session_id,
                "interaction_count": recent_session.interaction_count,
                "total_tokens": recent_session.total_tokens.model_dump(),
                "total_cost": float(
                    recent_session.calculate_total_cost(self.pricing_data)
                ),
                "models_used": recent_session.models_used,
            },
            "recent_interaction": {
                "file_name": recent_file.file_name,
                "model_id": recent_file.model_id,
                "tokens": recent_file.tokens.model_dump(),
                "cost": float(recent_file.calculate_cost(self.pricing_data)),
                "modification_time": recent_file.modification_time.isoformat(),
            }
            if recent_file
            else None,
            "burn_rate": self._calculate_burn_rate(recent_session),
            "context_usage": self._calculate_context_usage(recent_file)
            if recent_file
            else None,
        }

    def _calculate_context_usage(
        self, interaction_file: InteractionFile
    ) -> Dict[str, Any]:
        """Calculate context window usage for an interaction.

        Args:
            interaction_file: Interaction file to analyze

        Returns:
            Context usage information
        """
        if interaction_file.model_id not in self.pricing_data:
            return {
                "context_size": 0,
                "context_window": 200000,
                "usage_percentage": 0.0,
            }

        model_pricing = self.pricing_data[interaction_file.model_id]
        context_window = model_pricing.context_window

        # Context size = input + cache read + cache write
        context_size = (
            interaction_file.tokens.input
            + interaction_file.tokens.cache_read
            + interaction_file.tokens.cache_write
        )

        usage_percentage = (
            (context_size / context_window) * 100 if context_window > 0 else 0
        )

        return {
            "context_size": context_size,
            "context_window": context_window,
            "usage_percentage": min(100.0, usage_percentage),
        }

    def validate_monitoring_setup(self, base_path: str) -> Dict[str, Any]:
        """Validate that monitoring can be set up properly.

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Validation results
        """
        issues = []
        warnings = []

        # Check if base path exists
        base_path_obj = Path(base_path)
        if not base_path_obj.exists():
            issues.append(f"Base path does not exist: {base_path}")
            return {"valid": False, "issues": issues, "warnings": warnings}

        if not base_path_obj.is_dir():
            issues.append(f"Base path is not a directory: {base_path}")
            return {"valid": False, "issues": issues, "warnings": warnings}

        # Check for session directories
        session_dirs = self._find_sessions(base_path)
        if not session_dirs:
            warnings.append("No session directories found")
        else:
            # Check most recent session
            recent_session = self._load_session(session_dirs[0])
            if not recent_session:
                warnings.append("Most recent session directory contains no valid data")
            elif not recent_session.files:
                warnings.append("Most recent session has no interaction files")

        # Check pricing data
        if not self.pricing_data:
            warnings.append("No pricing data available - costs will show as $0.00")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "session_directories_found": len(session_dirs),
            "most_recent_session": session_dirs[0].name if session_dirs else None,
        }
