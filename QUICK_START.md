# Quick Start Guide

Get up and running with OmO Monitor in just a few minutes!

## Prerequisites

- Python 3.7 or higher
- pip package manager
- AI coding session data from one or more sources:
  - OpenCode: `~/.local/share/opencode/storage/message/`
  - Claude Code: `~/.claude/projects/`
  - Codex: `~/.codex/`

## Installation

### Linux/macOS

```bash
# Clone the repository
git clone https://github.com/yourusername/omo-monitor.git
cd omo-monitor

# Run the installation script
./install.sh
```

### Windows

```cmd
# Clone the repository
git clone https://github.com/yourusername/omo-monitor.git
cd omo-monitor

# Run the installation script
install.bat
```

### Manual Installation (All Platforms)

```bash
# Clone the repository
git clone https://github.com/yourusername/omo-monitor.git
cd omo-monitor

# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

## First Steps

### 1. Check Configuration
```bash
omo-monitor config show
```

### 2. Analyze Your Sessions
```bash
# Analyze all sessions (auto-detects sources)
omo-monitor sessions

# Use a specific source
omo-monitor sessions --source claude-code
omo-monitor sessions --source opencode

# Analyze all sources combined
omo-monitor sessions --source all
```

### 3. View Different Reports
```bash
# Daily usage breakdown
omo-monitor daily

# Model usage analytics
omo-monitor models

# Weekly breakdown
omo-monitor weekly
```

### 4. Real-time Monitoring
```bash
# Start live dashboard (last 24 hours)
omo-monitor live -H 24

# Monitor all sources
omo-monitor live --source all -H 24
```

### 5. Export Data
```bash
# Export to CSV
omo-monitor export sessions --format csv --output my_report.csv

# Export to JSON
omo-monitor export sessions --format json --output my_report.json
```

## Cache Management (v1.1.0+)

OmO Monitor uses DuckDB for fast session loading:

```bash
# View cache status
omo-monitor cache status

# Clear cache
omo-monitor cache clear

# Rebuild cache from scratch
omo-monitor cache rebuild
```

## Pricing Management (v1.1.0+)

Dynamic pricing from Models.dev API:

```bash
# View pricing configuration
omo-monitor pricing status

# Force refresh prices
omo-monitor pricing update

# List all available model prices
omo-monitor pricing list
```

## Common Commands

| Command | Description |
|---------|-------------|
| `omo-monitor --help` | Show all available commands |
| `omo-monitor config show` | Display current configuration |
| `omo-monitor sessions` | Analyze all sessions |
| `omo-monitor sessions --source all` | Analyze from all sources |
| `omo-monitor daily` | Daily usage breakdown |
| `omo-monitor models` | Model usage analytics |
| `omo-monitor live -H 24` | Real-time monitoring (24h) |
| `omo-monitor cache status` | Show cache statistics |
| `omo-monitor pricing update` | Refresh model prices |

## Data Sources

OmO Monitor supports multiple AI coding assistants:

| Source | Flag | Default Path |
|--------|------|--------------|
| OpenCode | `--source opencode` | `~/.local/share/opencode/storage/message/` |
| Claude Code | `--source claude-code` | `~/.claude/projects/` |
| Codex | `--source codex` | `~/.codex/` |
| All Sources | `--source all` | All detected sources |
| Auto-detect | `--source auto` | First available source |

## Need Help?

- Run `omo-monitor <command> --help` for specific command help
- Check `MANUAL_TEST_GUIDE.md` for comprehensive usage examples
- File an issue on GitHub if you encounter problems

## You're Ready!

Start exploring your AI coding session data and gain insights into your AI-assisted coding patterns!
