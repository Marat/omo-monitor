"""Textual-based live monitoring for OpenCode Monitor."""

import threading
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, Any, List, Set

from rich.panel import Panel
from rich.columns import Columns
from rich.tree import Tree

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static
from textual.containers import VerticalScroll
from textual.timer import Timer

import watchfiles

from ..models.session import TokenUsage
from ..models.limits import LimitsConfig
from ..utils.file_utils import FileProcessor
from ..config import ModelPricing


class StatsPanel(Static):
    """Widget displaying stats panel."""

    pass


class ProviderPanel(Static):
    """Widget displaying provider cards."""

    pass


class ProjectsPanel(Static):
    """Widget displaying project cards."""

    pass


class BreakdownPanel(VerticalScroll):
    """Scrollable widget displaying usage breakdown tree."""

    def compose(self) -> ComposeResult:
        """Create inner static widget for content."""
        yield Static(id="breakdown-content")

    def set_content(self, renderable) -> None:
        """Update the content inside the scroll container."""
        self.query_one("#breakdown-content", Static).update(renderable)


class StreamPanel(Static):
    """Widget displaying live stream."""

    pass


class AggregateMonitorApp(App):
    """Textual app for aggregate monitoring dashboard."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 4;
        grid-rows: 4 12 1fr 7;
    }
    
    #header-panel {
        column-span: 2;
        content-align: center middle;
    }
    
    #provider-panel {
        column-span: 2;
    }
    
    #projects-panel {
        column-span: 1;
    }
    
    #breakdown-panel {
        column-span: 1;
    }
    
    #stream-panel {
        column-span: 2;
    }
    
    StatsPanel {
        height: 100%;
        border: solid cyan;
        padding: 0 1;
    }
    
    ProviderPanel {
        height: 100%;
        border: solid blue;
        border-title-color: blue;
        padding: 0 1;
    }
    
    ProjectsPanel {
        height: 100%;
        border: solid cyan;
        border-title-color: cyan;
        padding: 0 1;
    }
    
    BreakdownPanel {
        height: 100%;
        border: solid magenta;
        border-title-color: magenta;
        padding: 0 1;
    }
    
    StreamPanel {
        height: 100%;
        border: solid $primary;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_pause", "Pause/Resume"),
        Binding("p", "cycle_project", "Project"),
        Binding("m", "cycle_model", "Model"),
        Binding("b", "toggle_breakdown", "Breakdown"),
        Binding("plus", "increase_interval", "+Interval"),
        Binding("equal", "increase_interval", "+Interval", show=False),
        Binding("minus", "decrease_interval", "-Interval"),
        Binding("question_mark", "help", "Help"),
    ]

    # Reactive state
    paused = reactive(False)
    refresh_interval = reactive(10)
    project_filter: reactive[Optional[str]] = reactive(None)  # None = all projects
    model_filter: reactive[Optional[str]] = reactive(None)  # None = all models
    breakdown_mode: reactive[str] = reactive("provider")  # "provider" or "agent"

    def __init__(
        self,
        base_path: str,
        pricing_data: Dict[str, ModelPricing],
        limits_config: Optional[LimitsConfig] = None,
        refresh_interval: int = 10,
        hours_filter: Optional[float] = None,
    ):
        super().__init__()
        self.base_path = base_path
        self.pricing_data = pricing_data
        self.limits_config = limits_config
        self.refresh_interval = refresh_interval
        self.hours_filter = hours_filter  # None = today only, 0 = fresh start
        self._update_timer: Optional[Timer] = None
        self._loading = False

        # Fixed cutoff time (calculated once at startup)
        now = datetime.now()
        if hours_filter:
            self._fixed_cutoff = now - timedelta(hours=hours_filter)
        else:
            self._fixed_cutoff = datetime.combine(now.date(), datetime.min.time())

        # Cache for incremental updates
        self._cached_data: Optional[Dict[str, Any]] = None
        self._session_cache: Dict[
            str, Dict[str, Any]
        ] = {}  # session_id -> session data
        self._changed_sessions: Set[str] = set()  # sessions that need reload

        # File watcher
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_watcher = threading.Event()

        # Available projects and models for filtering
        self._available_projects: List[str] = []
        self._available_models: List[str] = []

        # Error tracking
        self._error_count: int = 0
        self._last_error_count: int = 0

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)

        header_panel = StatsPanel(id="header-panel")
        header_panel.border_title = "OCMONITOR AGGREGATE"
        yield header_panel

        provider_panel = ProviderPanel(id="provider-panel")
        provider_panel.border_title = "Provider Limits"
        yield provider_panel

        projects_panel = ProjectsPanel(id="projects-panel")
        projects_panel.border_title = "Active Projects"
        yield projects_panel

        breakdown_panel = BreakdownPanel(id="breakdown-panel")
        breakdown_panel.border_title = "Breakdown"
        yield breakdown_panel

        stream_panel = StreamPanel(id="stream-panel")
        stream_panel.border_title = "Live Stream"
        yield stream_panel

        yield Footer()

    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Start file watcher in background thread
        self._start_watcher()
        # Initial full load
        self._do_update(full_reload=True)
        # Periodic UI refresh (uses cached data + changes)
        self._update_timer = self.set_interval(self.refresh_interval, self._do_update)

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        self._stop_watcher.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=1)

    def _start_watcher(self) -> None:
        """Start file system watcher in background."""
        base_path = Path(self.base_path).expanduser()

        def watch_loop():
            try:
                for changes in watchfiles.watch(
                    base_path,
                    stop_event=self._stop_watcher,
                    recursive=True,
                ):
                    for change_type, path in changes:
                        # Extract session ID from path (e.g., .../ses_xxx/file.json)
                        path_obj = Path(path)
                        for parent in path_obj.parents:
                            if parent.name.startswith("ses_"):
                                self._changed_sessions.add(str(parent))
                                break
            except Exception:
                pass  # Watcher stopped

        self._watcher_thread = threading.Thread(target=watch_loop, daemon=True)
        self._watcher_thread.start()

    def _do_update(self, full_reload: bool = False) -> None:
        """Trigger async data load."""
        if self.paused or self._loading:
            return
        self._loading = True

        # Collect changed sessions and clear the set
        changed = set(self._changed_sessions)
        self._changed_sessions.clear()

        self.run_worker(
            lambda: self._load_data(full_reload=full_reload, changed_sessions=changed),
            thread=True,
        )

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion."""
        if event.state.name == "SUCCESS" and event.worker.result:
            self._update_ui(event.worker.result)
            self._loading = False
        elif event.state.name in ("ERROR", "CANCELLED"):
            self._loading = False
            if event.state.name == "ERROR":
                self.notify(f"Load error", timeout=3)

    def _load_data(
        self, full_reload: bool = False, changed_sessions: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """Data loading (runs in worker thread).

        If full_reload or no cache, does full scan.
        Otherwise only reloads changed sessions and merges with cache.
        """
        now = datetime.now()
        cutoff = self._get_cutoff_time()

        # Decide what to reload
        if full_reload or not self._cached_data:
            sessions_to_load = self._get_sessions_for_full_load()
            self._session_cache.clear()
        else:
            # Check for new sessions not in cache + changed sessions
            sessions_to_load = []

            # Add changed sessions from watcher
            if changed_sessions:
                sessions_to_load.extend(
                    [Path(s) for s in changed_sessions if Path(s).exists()]
                )

            # Quick scan for new sessions (not in cache)
            new_sessions = self._find_new_sessions()
            sessions_to_load.extend(new_sessions)

            if not sessions_to_load:
                # No changes, use cached data with updated timestamp
                if self._cached_data:
                    self._cached_data["now"] = now
                    return self._cached_data
                sessions_to_load = self._get_sessions_for_full_load()

        # Load/reload sessions
        for session_dir in sessions_to_load:
            session_data = self._load_single_session(session_dir, cutoff)
            session_id = str(session_dir)
            if session_data:
                self._session_cache[session_id] = session_data
            elif session_id in self._session_cache:
                # Session no longer has today's data, remove from cache
                del self._session_cache[session_id]

        # Aggregate from cache
        return self._aggregate_from_cache(now)

    def _find_new_sessions(self) -> List[Path]:
        """Find sessions that exist but aren't in cache (new sessions).

        Uses directory mtime for quick check - only loads session if dir is recent.
        """
        base_path = Path(self.base_path).expanduser()
        if not base_path.exists():
            return []

        cutoff = self._get_cutoff_time()
        cutoff_ts = cutoff.timestamp()
        cached_ids = set(self._session_cache.keys())
        new_sessions = []

        # Quick scan using directory mtime (no file loading)
        try:
            for entry in base_path.iterdir():
                if not entry.is_dir() or not entry.name.startswith("ses_"):
                    continue

                session_id = str(entry)
                if session_id in cached_ids:
                    continue

                # Check dir mtime - if modified after cutoff, it might have new data
                if entry.stat().st_mtime >= cutoff_ts:
                    new_sessions.append(entry)

                # Limit how many new sessions we check
                if len(new_sessions) >= 10:
                    break
        except OSError:
            pass

        return new_sessions

    def _get_cutoff_time(self) -> datetime:
        """Get fixed cutoff time (calculated once at startup)."""
        return self._fixed_cutoff

    def _get_sessions_for_full_load(self) -> List[Path]:
        """Get list of sessions for full load with optimization."""
        session_dirs = FileProcessor.find_session_directories(self.base_path)
        cutoff = self._get_cutoff_time()

        # Scan limits (generous for large time ranges)
        max_sessions = 2000
        max_consecutive_misses = 100
        consecutive_misses = 0
        result = []
        error_count = 0

        for session_dir in session_dirs[:max_sessions]:
            try:
                session = FileProcessor.load_session_data(session_dir)
                if not session or not session.files:
                    consecutive_misses += 1
                    if consecutive_misses >= max_consecutive_misses:
                        break
                    continue

                has_recent = any(
                    f.modification_time and f.modification_time >= cutoff
                    for f in session.files
                )
                if has_recent:
                    result.append(session_dir)
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
                    if consecutive_misses >= max_consecutive_misses:
                        break
            except Exception:
                # Skip sessions with parsing errors
                error_count += 1
                consecutive_misses += 1
                if consecutive_misses >= max_consecutive_misses:
                    break
                continue

        self._error_count = error_count
        return result

    def _load_single_session(
        self, session_dir: Path, cutoff: datetime
    ) -> Optional[Dict[str, Any]]:
        """Load data for a single session."""
        try:
            session = FileProcessor.load_session_data(session_dir)
            if not session or not session.files:
                return None

            recent_files = [
                f
                for f in session.files
                if f.modification_time and f.modification_time >= cutoff
            ]

            if not recent_files:
                return None

            return {
                "project_name": session.project_name,
                "files": recent_files,
                "session": session,
            }
        except Exception:
            # Skip sessions with parsing errors
            self._error_count += 1
            return None

    def _aggregate_from_cache(self, now: datetime) -> Dict[str, Any]:
        """Aggregate stats from session cache."""
        project_stats: Dict[str, Dict[str, Any]] = {}
        provider_usage: Dict[str, Dict[str, Any]] = {}
        usage_hierarchy: Dict[str, Any] = {}

        total_tokens = TokenUsage()
        total_cost = Decimal("0.0")
        total_sessions = 0
        total_interactions = 0
        recent_files: List[tuple] = []

        for session_id, session_data in self._session_cache.items():
            try:
                project_name = session_data["project_name"]
                today_files = session_data["files"]
                session = session_data["session"]
            except (KeyError, TypeError):
                continue  # Skip malformed cache entries

            if project_name not in project_stats:
                project_stats[project_name] = {
                    "sessions": 0,
                    "interactions": 0,
                    "tokens": TokenUsage(),
                    "cost": Decimal("0.0"),
                    "latest_time": None,
                    "latest_model": None,
                    "cache_rate": 0.0,
                }

            stats = project_stats[project_name]
            stats["sessions"] += 1
            stats["interactions"] += len(today_files)
            total_sessions += 1
            total_interactions += len(today_files)

            for file in today_files:
                try:
                    stats["tokens"].input += file.tokens.input
                    stats["tokens"].output += file.tokens.output
                    stats["tokens"].cache_write += file.tokens.cache_write
                    stats["tokens"].cache_read += file.tokens.cache_read

                    total_tokens.input += file.tokens.input
                    total_tokens.output += file.tokens.output
                    total_tokens.cache_write += file.tokens.cache_write
                    total_tokens.cache_read += file.tokens.cache_read

                    file_cost = file.calculate_cost(self.pricing_data)
                    stats["cost"] += file_cost
                    total_cost += file_cost

                    provider_id = file.provider_id or (
                        file.model_id.split("/")[0]
                        if "/" in file.model_id
                        else "unknown"
                    )

                    if provider_id not in provider_usage:
                        provider_usage[provider_id] = {
                            "requests": 0,
                            "tokens": 0,
                            "cost": Decimal("0.0"),
                        }

                    provider_usage[provider_id]["requests"] += 1
                    provider_usage[provider_id]["tokens"] += file.tokens.total
                    provider_usage[provider_id]["cost"] += file_cost

                    # Hierarchical tracking
                    model_name = (
                        file.model_id.split("/")[-1]
                        if "/" in file.model_id
                        else file.model_id
                    )
                    agent_name = file.agent or "unknown"
                    category_name = file.category or "unknown"

                    if provider_id not in usage_hierarchy:
                        usage_hierarchy[provider_id] = {}
                    if model_name not in usage_hierarchy[provider_id]:
                        usage_hierarchy[provider_id][model_name] = {}
                    if agent_name not in usage_hierarchy[provider_id][model_name]:
                        usage_hierarchy[provider_id][model_name][agent_name] = {}
                    if (
                        category_name
                        not in usage_hierarchy[provider_id][model_name][agent_name]
                    ):
                        usage_hierarchy[provider_id][model_name][agent_name][
                            category_name
                        ] = {"requests": 0, "cost": Decimal("0.0")}

                    usage_hierarchy[provider_id][model_name][agent_name][category_name][
                        "requests"
                    ] += 1
                    usage_hierarchy[provider_id][model_name][agent_name][category_name][
                        "cost"
                    ] += file_cost

                    if (
                        stats["latest_time"] is None
                        or file.modification_time > stats["latest_time"]
                    ):
                        stats["latest_time"] = file.modification_time
                        stats["latest_model"] = model_name

                    recent_files.append((project_name, file, session))
                except Exception:
                    # Skip files with processing errors
                    continue

            # Cache rate for this project
            total_input = stats["tokens"].input + stats["tokens"].cache_read
            if total_input > 0:
                stats["cache_rate"] = (stats["tokens"].cache_read / total_input) * 100

        recent_files.sort(key=lambda x: x[1].modification_time, reverse=True)

        # Collect available models from hierarchy (sorted by request count)
        model_requests: Dict[str, int] = {}
        for provider_data in usage_hierarchy.values():
            for model_name, agents_data in provider_data.items():
                reqs = sum(
                    sum(c["requests"] for c in a.values()) for a in agents_data.values()
                )
                model_requests[model_name] = model_requests.get(model_name, 0) + reqs
        self._available_models = sorted(
            model_requests.keys(), key=lambda m: model_requests[m], reverse=True
        )

        result = {
            "project_stats": project_stats,
            "provider_usage": provider_usage,
            "usage_hierarchy": usage_hierarchy,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "total_sessions": total_sessions,
            "total_interactions": total_interactions,
            "recent_files": recent_files,
            "now": now,
            "error_count": self._error_count,
        }
        self._cached_data = result
        return result

    def _build_project_hierarchy(self, project_name: str) -> Dict[str, Any]:
        """Build usage hierarchy for a specific project from cache."""
        usage_hierarchy: Dict[str, Any] = {}

        for session_id, session_data in self._session_cache.items():
            if session_data["project_name"] != project_name:
                continue

            for file in session_data["files"]:
                provider_id = file.provider_id or (
                    file.model_id.split("/")[0] if "/" in file.model_id else "unknown"
                )
                model_name = (
                    file.model_id.split("/")[-1]
                    if "/" in file.model_id
                    else file.model_id
                )
                agent_name = file.agent or "unknown"
                category_name = file.category or "unknown"
                file_cost = file.calculate_cost(self.pricing_data)

                if provider_id not in usage_hierarchy:
                    usage_hierarchy[provider_id] = {}
                if model_name not in usage_hierarchy[provider_id]:
                    usage_hierarchy[provider_id][model_name] = {}
                if agent_name not in usage_hierarchy[provider_id][model_name]:
                    usage_hierarchy[provider_id][model_name][agent_name] = {}
                if (
                    category_name
                    not in usage_hierarchy[provider_id][model_name][agent_name]
                ):
                    usage_hierarchy[provider_id][model_name][agent_name][
                        category_name
                    ] = {"requests": 0, "cost": Decimal("0.0")}

                usage_hierarchy[provider_id][model_name][agent_name][category_name][
                    "requests"
                ] += 1
                usage_hierarchy[provider_id][model_name][agent_name][category_name][
                    "cost"
                ] += file_cost

        return usage_hierarchy

    def _build_agent_hierarchy(
        self, project_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build usage hierarchy by Agent -> Category -> Provider/Model from cache."""
        agent_hierarchy: Dict[str, Any] = {}

        for session_id, session_data in self._session_cache.items():
            if project_filter and session_data["project_name"] != project_filter:
                continue

            for file in session_data["files"]:
                provider_id = file.provider_id or (
                    file.model_id.split("/")[0] if "/" in file.model_id else "unknown"
                )
                model_name = (
                    file.model_id.split("/")[-1]
                    if "/" in file.model_id
                    else file.model_id
                )
                agent_name = file.agent or "unknown"
                category_name = file.category or "unknown"
                file_cost = file.calculate_cost(self.pricing_data)

                # Agent -> Category -> Provider -> Model
                if agent_name not in agent_hierarchy:
                    agent_hierarchy[agent_name] = {}
                if category_name not in agent_hierarchy[agent_name]:
                    agent_hierarchy[agent_name][category_name] = {}
                if provider_id not in agent_hierarchy[agent_name][category_name]:
                    agent_hierarchy[agent_name][category_name][provider_id] = {}
                if (
                    model_name
                    not in agent_hierarchy[agent_name][category_name][provider_id]
                ):
                    agent_hierarchy[agent_name][category_name][provider_id][
                        model_name
                    ] = {"requests": 0, "cost": Decimal("0.0")}

                agent_hierarchy[agent_name][category_name][provider_id][model_name][
                    "requests"
                ] += 1
                agent_hierarchy[agent_name][category_name][provider_id][model_name][
                    "cost"
                ] += file_cost

        return agent_hierarchy

    def _update_ui(self, data: Dict[str, Any]) -> None:
        """Update UI with loaded data - runs on main thread."""
        project_stats = data["project_stats"]
        provider_usage = data["provider_usage"]
        usage_hierarchy = data["usage_hierarchy"]
        total_cost = data["total_cost"]
        total_sessions = data["total_sessions"]
        total_interactions = data["total_interactions"]
        recent_files = data["recent_files"]
        now = data["now"]
        error_count = data.get("error_count", 0)

        # Update available projects for filtering (sorted by cost)
        self._available_projects = sorted(
            project_stats.keys(), key=lambda p: project_stats[p]["cost"], reverse=True
        )

        # Update header panel
        status = "[green]NOMINAL[/green]"
        pause_status = "[yellow]PAUSED[/yellow]" if self.paused else ""

        # Format time filter display
        if self.hours_filter is not None:
            if self.hours_filter < 0.017:  # ~1 minute
                time_filter = "[cyan]fresh[/cyan]"
            elif self.hours_filter < 1:
                minutes = int(self.hours_filter * 60)
                time_filter = f"[cyan]{minutes}m[/cyan]"
            else:
                time_filter = f"[cyan]{self.hours_filter:.0f}h[/cyan]"
        else:
            time_filter = "[dim]today[/dim]"

        # Error indicator
        error_indicator = ""
        if error_count > 0:
            error_indicator = f"  [dim]|[/dim]  [red]{error_count} err[/red]"

        header_text = (
            f"[bold white]${total_cost:.2f}[/bold white] [dim]cost[/dim]  "
            f"[dim]|[/dim]  [bold white]{total_sessions}[/bold white] [dim]sessions[/dim]  "
            f"[dim]|[/dim]  [bold white]{total_interactions:,}[/bold white] [dim]interactions[/dim]  "
            f"[dim]|[/dim]  {time_filter}  "
            f"[dim]|[/dim]  {status} {pause_status}{error_indicator}  "
            f"[dim]|[/dim]  [dim]{self.refresh_interval}s[/dim]"
        )
        header_panel = self.query_one("#header-panel", StatsPanel)
        header_panel.update(header_text)

        # Update provider panel
        provider_cards = []
        for provider_id, usage in sorted(
            provider_usage.items(), key=lambda x: x[1]["cost"], reverse=True
        ):
            card_text = (
                f"[dim]Requests:[/dim] [white]{usage['requests']:,}[/white]\n"
                f"[dim]Tokens:[/dim] [white]{usage['tokens']:,}[/white]\n"
                f"[dim]Cost:[/dim] [green]${usage['cost']:.2f}[/green]"
            )
            provider_cards.append(
                Panel(card_text, title=provider_id, border_style="dim")
            )

        if provider_cards:
            self.query_one("#provider-panel", ProviderPanel).update(
                Columns(provider_cards, equal=True, expand=True)
            )
        else:
            self.query_one("#provider-panel", ProviderPanel).update(
                "[dim]No provider data[/dim]"
            )

        # Update projects panel
        project_cards = []
        sorted_projects = sorted(
            project_stats.items(), key=lambda x: x[1]["cost"], reverse=True
        )

        for project_name, pstats in sorted_projects:
            if pstats["latest_time"]:
                delta = now - pstats["latest_time"]
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

            display_name = (
                project_name[:18] + ".." if len(project_name) > 20 else project_name
            )
            card_lines = [
                f"{status_icon} [dim]{time_ago} ago[/dim]",
                f"[dim]Sess:[/dim] {pstats['sessions']}  [dim]Req:[/dim] {pstats['interactions']}",
                f"[green]${pstats['cost']:.2f}[/green]",
            ]
            project_cards.append(
                Panel(
                    "\n".join(card_lines), title=display_name, border_style="dim cyan"
                )
            )

        if project_cards:
            self.query_one("#projects-panel", ProjectsPanel).update(
                Columns(project_cards, equal=True, expand=True)
            )
        else:
            self.query_one("#projects-panel", ProjectsPanel).update(
                "[dim]No active projects today[/dim]"
            )

        # Update breakdown panel - filter by project and/or model
        breakdown_panel = self.query_one("#breakdown-panel", BreakdownPanel)

        # Build title with active filters and mode
        mode_label = "P→M→A→C" if self.breakdown_mode == "provider" else "A→C→P→M"
        filter_parts = [mode_label]
        if self.project_filter:
            filter_parts.append(self.project_filter)
        if self.model_filter:
            filter_parts.append(f"M:{self.model_filter[:15]}")
        filter_label = ", ".join(filter_parts)
        breakdown_panel.border_title = f"Breakdown [{filter_label}]"

        usage_tree = Tree("[bold]Usage Breakdown[/bold]")

        if self.breakdown_mode == "provider":
            # Provider → Model → Agent → Category
            if self.project_filter:
                filtered_hierarchy = self._build_project_hierarchy(self.project_filter)
            else:
                filtered_hierarchy = usage_hierarchy

            if filtered_hierarchy:
                for provider_id, models_data in sorted(
                    filtered_hierarchy.items(),
                    key=lambda x: sum(
                        sum(cat["cost"] for cat in agent.values())
                        for model in x[1].values()
                        for agent in model.values()
                        if not self.model_filter or model == self.model_filter
                    ),
                    reverse=True,
                ):
                    # Apply model filter
                    filtered_models = {
                        m: a
                        for m, a in models_data.items()
                        if not self.model_filter or m == self.model_filter
                    }
                    if not filtered_models:
                        continue

                    p_cost = sum(
                        sum(cat["cost"] for cat in agent.values())
                        for model in filtered_models.values()
                        for agent in model.values()
                    )
                    p_reqs = sum(
                        sum(cat["requests"] for cat in agent.values())
                        for model in filtered_models.values()
                        for agent in model.values()
                    )
                    provider_branch = usage_tree.add(
                        f"[cyan]{provider_id}[/cyan] [dim]({p_reqs} req, ${p_cost:.2f})[/dim]"
                    )

                    for model_name, agents_data in sorted(
                        filtered_models.items(),
                        key=lambda x: sum(
                            sum(c["cost"] for c in a.values()) for a in x[1].values()
                        ),
                        reverse=True,
                    ):
                        m_reqs = sum(
                            sum(c["requests"] for c in a.values())
                            for a in agents_data.values()
                        )
                        model_branch = provider_branch.add(
                            f"[white]{model_name}[/white] [dim]({m_reqs} req)[/dim]"
                        )

                        for agent_name, categories_data in sorted(
                            agents_data.items(),
                            key=lambda x: sum(c["requests"] for c in x[1].values()),
                            reverse=True,
                        ):
                            a_reqs = sum(
                                c["requests"] for c in categories_data.values()
                            )
                            agent_branch = model_branch.add(
                                f"[magenta]{agent_name}[/magenta] [dim]({a_reqs} req)[/dim]"
                            )

                            for cat_name, cat_stats in sorted(
                                categories_data.items(),
                                key=lambda x: x[1]["requests"],
                                reverse=True,
                            ):
                                agent_branch.add(
                                    f"[yellow]{cat_name}[/yellow]: {cat_stats['requests']} req"
                                )
            else:
                usage_tree.add("[dim]No data[/dim]")
        else:
            # Agent → Category → Provider → Model
            agent_hierarchy = self._build_agent_hierarchy(self.project_filter)

            if agent_hierarchy:
                for agent_name, categories_data in sorted(
                    agent_hierarchy.items(),
                    key=lambda x: sum(
                        sum(m["cost"] for m in p.values())
                        for cat in x[1].values()
                        for p in cat.values()
                    ),
                    reverse=True,
                ):
                    a_cost = sum(
                        sum(m["cost"] for m in p.values())
                        for cat in categories_data.values()
                        for p in cat.values()
                    )
                    a_reqs = sum(
                        sum(m["requests"] for m in p.values())
                        for cat in categories_data.values()
                        for p in cat.values()
                    )
                    agent_branch = usage_tree.add(
                        f"[magenta]{agent_name}[/magenta] [dim]({a_reqs} req, ${a_cost:.2f})[/dim]"
                    )

                    for cat_name, providers_data in sorted(
                        categories_data.items(),
                        key=lambda x: sum(
                            sum(m["requests"] for m in p.values())
                            for p in x[1].values()
                        ),
                        reverse=True,
                    ):
                        c_reqs = sum(
                            sum(m["requests"] for m in p.values())
                            for p in providers_data.values()
                        )
                        cat_branch = agent_branch.add(
                            f"[yellow]{cat_name}[/yellow] [dim]({c_reqs} req)[/dim]"
                        )

                        for provider_id, models_data in sorted(
                            providers_data.items(),
                            key=lambda x: sum(m["requests"] for m in x[1].values()),
                            reverse=True,
                        ):
                            # Apply model filter
                            filtered_models = {
                                m: s
                                for m, s in models_data.items()
                                if not self.model_filter or m == self.model_filter
                            }
                            if not filtered_models:
                                continue

                            p_reqs = sum(
                                m["requests"] for m in filtered_models.values()
                            )
                            provider_branch = cat_branch.add(
                                f"[cyan]{provider_id}[/cyan] [dim]({p_reqs} req)[/dim]"
                            )

                            for model_name, model_stats in sorted(
                                filtered_models.items(),
                                key=lambda x: x[1]["requests"],
                                reverse=True,
                            ):
                                provider_branch.add(
                                    f"[white]{model_name}[/white]: {model_stats['requests']} req"
                                )
            else:
                usage_tree.add("[dim]No data[/dim]")

        self.query_one("#breakdown-panel", BreakdownPanel).set_content(usage_tree)

        # Update stream panel
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
                file.model_id.split("/")[-1] if "/" in file.model_id else file.model_id
            )
            stream_lines.append(
                f"[dim]{time_str}[/dim] [cyan]{short_project:<14}[/cyan] "
                f"[white]{file.tokens.total:>8,}[/white] [dim]tok[/dim]  "
                f"[dim]({model_short})[/dim]"
            )

        stream_text = (
            "\n".join(stream_lines) if stream_lines else "[dim]No recent activity[/dim]"
        )
        self.query_one("#stream-panel", StreamPanel).update(stream_text)

    # Actions - use call_later so keys respond immediately
    def action_refresh(self) -> None:
        """Force refresh."""
        self.notify("Refreshing...")
        self.call_later(self._do_update)

    def action_toggle_pause(self) -> None:
        """Toggle pause."""
        self.paused = not self.paused
        status = "PAUSED" if self.paused else "RUNNING"
        self.notify(f"Status: {status}")

    def action_increase_interval(self) -> None:
        """Increase refresh interval."""
        self.refresh_interval = min(60, self.refresh_interval + 5)
        if self._update_timer:
            self._update_timer.stop()
            self._update_timer = self.set_interval(
                self.refresh_interval, self._do_update
            )
        self.notify(f"Interval: {self.refresh_interval}s")

    def action_decrease_interval(self) -> None:
        """Decrease refresh interval."""
        self.refresh_interval = max(2, self.refresh_interval - 5)
        if self._update_timer:
            self._update_timer.stop()
            self._update_timer = self.set_interval(
                self.refresh_interval, self._do_update
            )
        self.notify(f"Interval: {self.refresh_interval}s")

    def action_cycle_project(self) -> None:
        """Cycle through projects for breakdown filter."""
        if not self._available_projects:
            self.notify("No projects available")
            return

        if self.project_filter is None:
            # Start with first project
            self.project_filter = self._available_projects[0]
        else:
            try:
                idx = self._available_projects.index(self.project_filter)
                idx = (idx + 1) % (len(self._available_projects) + 1)
                if idx == len(self._available_projects):
                    self.project_filter = None  # Reset to all
                else:
                    self.project_filter = self._available_projects[idx]
            except ValueError:
                self.project_filter = None

        filter_name = self.project_filter or "all"
        self.notify(f"Project: {filter_name}")

        # Update UI immediately with cached data
        if self._cached_data:
            self._update_ui(self._cached_data)

    def action_cycle_model(self) -> None:
        """Cycle through models for breakdown filter."""
        if not self._available_models:
            self.notify("No models available")
            return

        if self.model_filter is None:
            # Start with first model
            self.model_filter = self._available_models[0]
        else:
            try:
                idx = self._available_models.index(self.model_filter)
                idx = (idx + 1) % (len(self._available_models) + 1)
                if idx == len(self._available_models):
                    self.model_filter = None  # Reset to all
                else:
                    self.model_filter = self._available_models[idx]
            except ValueError:
                self.model_filter = None

        filter_name = self.model_filter[:20] if self.model_filter else "all"
        self.notify(f"Model: {filter_name}")

        # Update UI immediately with cached data
        if self._cached_data:
            self._update_ui(self._cached_data)

    def action_toggle_breakdown(self) -> None:
        """Toggle breakdown mode between provider-first and agent-first."""
        if self.breakdown_mode == "provider":
            self.breakdown_mode = "agent"
            self.notify("Breakdown: Agent → Category → Provider → Model")
        else:
            self.breakdown_mode = "provider"
            self.notify("Breakdown: Provider → Model → Agent → Category")

        # Update UI immediately with cached data
        if self._cached_data:
            self._update_ui(self._cached_data)

    def action_help(self) -> None:
        """Show help."""
        self.notify(
            "Q=Quit R=Refresh Space=Pause P=Project M=Model B=Breakdown +/-=Interval",
            timeout=5,
        )


def run_textual_monitor(
    base_path: str,
    pricing_data: Dict[str, ModelPricing],
    limits_config: Optional[LimitsConfig] = None,
    refresh_interval: int = 10,
    hours_filter: Optional[float] = None,
) -> None:
    """Run the Textual-based aggregate monitor.

    Args:
        base_path: Path to messages directory
        pricing_data: Model pricing configuration
        limits_config: Provider limits configuration
        refresh_interval: UI refresh interval in seconds
        hours_filter: Show data from last N hours (None = today only, supports float for minutes)
    """
    app = AggregateMonitorApp(
        base_path=base_path,
        pricing_data=pricing_data,
        limits_config=limits_config,
        refresh_interval=refresh_interval,
        hours_filter=hours_filter,
    )
    app.run()
