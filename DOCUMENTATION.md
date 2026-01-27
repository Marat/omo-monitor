# 📚 OpenCode Monitor - Complete Documentation

Welcome to the complete documentation for OpenCode Monitor, a powerful CLI tool for monitoring and analyzing your OpenCode AI coding sessions.

> **📸 Screenshots**: Throughout this documentation, you'll find clickable screenshot references that show actual command outputs. These screenshots are located in the `screenshots/` directory. To add your own screenshots, replace the placeholder PNG files with actual screenshots of your terminal output.

**🆕 Recent Updates**: This documentation reflects the latest improvements including professional UI redesign, project analytics, session time tracking, and enhanced live dashboard features.

## 📖 Table of Contents

1. [Installation](#installation)
2. [Basic Usage](#basic-usage)
3. [Command Reference](#command-reference)
4. [Configuration](#configuration)
5. [Adding New Models](#adding-new-models)
6. [Setting Usage Quotas](#setting-usage-quotas)
7. [Exporting Reports](#exporting-reports)
8. [Configuration Commands](#configuration-commands)
9. [Troubleshooting](#troubleshooting)
10. [Advanced Tips](#advanced-tips)

---

## 🚀 Installation

### Prerequisites

Before installing OpenCode Monitor, ensure you have:
- **Python 3.7+** installed on your system
- **pip** package manager
- **OpenCode AI** installed and configured

### Method 1: Automated Installation (Recommended)

The easiest way to install OpenCode Monitor:

```bash
# Clone the repository
git clone https://github.com/yourusername/omo-monitor.git
cd omo-monitor

# Run the automated installer
./install.sh
```

The installer will:
- ✅ Check Python version compatibility
- ✅ Install all required dependencies
- ✅ Configure PATH settings automatically
- ✅ Verify the installation

### Method 2: Manual Installation

For more control over the installation process:

```bash
# Clone the repository
git clone https://github.com/yourusername/omo-monitor.git
cd omo-monitor

# Install Python dependencies
python3 -m pip install -r requirements.txt

# Install the package in development mode
python3 -m pip install -e .
```

### Verify Installation

After installation, verify everything works:

```bash
# Check if omo-monitor is accessible
omo-monitor --help

# Test with sample data
omo-monitor sessions test_sessions/
```

### Configuration Setup

After installation, set up your personal configuration:

```bash
# Create configuration directory
mkdir -p ~/.config/omo-monitor

# Copy default configuration (if available in project)
cp config.toml ~/.config/omo_monitor/config.toml

# Or create a new configuration file
touch ~/.config/omo_monitor/config.toml

# Edit your configuration
nano ~/.config/omo_monitor/config.toml
```

Your configuration file should contain:
```toml
[paths]
messages_dir = "~/.local/share/opencode/storage/message"
export_dir = "./exports"

[ui]
table_style = "rich"
progress_bars = true
colors = true
```

### PATH Configuration (If Needed)

If you get "command not found" errors:

```bash
# Find your Python user base
python3 -m site --user-base

# Add to your shell profile (~/.bashrc or ~/.zshrc)
export PATH="$(python3 -m site --user-base)/bin:$PATH"

# Reload your shell
source ~/.bashrc  # or ~/.zshrc
```

---

## 🎯 Basic Usage

### Quick Start Example

```bash
# Show current configuration
omo-monitor config show

# Analyze all your sessions
omo-monitor sessions ~/.local/share/opencode/storage/message

# Get a weekly breakdown
omo-monitor weekly ~/.local/share/opencode/storage/message

# Start live monitoring
omo-monitor live ~/.local/share/opencode/storage/message
```

### Default OpenCode Message Location

By default, OpenCode stores messages at:
```
~/.local/share/opencode/storage/message
```

You can use this path in all commands, or configure a custom path (see [Configuration](#configuration) section).

---

## 📋 Command Reference

### 1. Session Analysis Commands

#### `omo-monitor session <path>`
Analyze a single coding session in detail.

```bash
# Analyze a specific session directory
omo-monitor session ~/.local/share/opencode/storage/message/ses_20250118_143022

# With JSON output
omo-monitor session ~/.local/share/opencode/storage/message/ses_20250118_143022 --format json
```

**Example Output:**

[![Session Analysis Screenshot](screenshots/session-analysis.png)](screenshots/session-analysis.png)

*Click image to view full-size screenshot of session analysis output*


```

#### `omo-monitor sessions <path>`
Analyze all sessions in a directory with summary statistics.

```bash
# Analyze all sessions
omo-monitor sessions ~/.local/share/opencode/storage/message

# Limit to recent sessions
omo-monitor sessions ~/.local/share/opencode/storage/message --limit 10

# JSON format for programmatic use
omo-monitor sessions ~/.local/share/opencode/storage/message --format json
```

**Example Output:**

[![Sessions Summary Screenshot](screenshots/sessions-summary.png)](screenshots/sessions-summary.png)

*Click image to view full-size screenshot of sessions summary output*

```

### 2. Time-Based Analysis Commands

#### `omo-monitor daily <path>`
Daily usage breakdown with cost and token analysis.

```bash
# Daily breakdown
omo-monitor daily ~/.local/share/opencode/storage/message

# With per-model breakdown
omo-monitor daily ~/.local/share/opencode/storage/message --breakdown

# JSON output
omo-monitor daily ~/.local/share/opencode/storage/message --format json
```

**Example Output:**

[![Daily Usage Breakdown Screenshot](screenshots/daily-usage-breakdown.png)](screenshots/daily-usage-breakdown.png)

*Click image to view full-size screenshot of daily usage breakdown*

```

#### `omo-monitor weekly <path> [--start-day <day>]`
Weekly usage patterns and trends with customizable week start days.

```bash
# Default (Monday start)
omo-monitor weekly ~/.local/share/opencode/storage/message

# Custom week start days
omo-monitor weekly ~/.local/share/opencode/storage/message --start-day sunday
omo-monitor weekly ~/.local/share/opencode/storage/message --start-day friday

# With per-model breakdown
omo-monitor weekly ~/.local/share/opencode/storage/message --start-day sunday --breakdown

# Specific year with custom week start
omo-monitor weekly ~/.local/share/opencode/storage/message --year 2025 --start-day wednesday
```

**Supported Days:** `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`

**Features:**
- 📅 Customize week boundaries to match your calendar preference
- 🗓️ US standard (Sunday), European (Monday), business week (Friday), etc.
- 📊 Date range display shows actual week boundaries
- 🎯 Table title indicates selected week start day

#### `omo-monitor monthly <path>`
Monthly usage analysis and cost tracking.

```bash
# Monthly breakdown
omo-monitor monthly ~/.local/share/opencode/storage/message

# With per-model breakdown
omo-monitor monthly ~/.local/share/opencode/storage/message --breakdown
```

### 3. Model Analysis Commands

#### `omo-monitor models <path>`
Detailed breakdown of usage per AI model.

```bash
# Model usage statistics
omo-monitor models ~/.local/share/opencode/storage/message

# JSON format
omo-monitor models ~/.local/share/opencode/storage/message --format json
```

**Example Output:**

[![Model Usage Analysis Screenshot](screenshots/model-usage-analysis.png)](screenshots/model-usage-analysis.png)

*Click image to view full-size screenshot of model usage analytics*

#### `omo-monitor projects <path>`
Analyze AI usage costs and token consumption by coding project.

```bash
# Project usage breakdown
omo-monitor projects ~/.local/share/opencode/storage/message

# Filter by date range
omo-monitor projects ~/.local/share/opencode/storage/message --start-date 2024-01-01 --end-date 2024-01-31

# JSON format for detailed analysis
omo-monitor projects ~/.local/share/opencode/storage/message --format json

# CSV format for spreadsheet analysis
omo-monitor projects ~/.local/share/opencode/storage/message --format csv
```

**Features:**
- 📊 **Project Breakdown** - Shows sessions, interactions, tokens, and costs per project
- 📈 **Summary Statistics** - Total projects, sessions, interactions, tokens, and cost
- 📅 **Activity Tracking** - First and last activity dates for each project
- 🤖 **Model Usage** - Lists AI models used for each project
- 📤 **Export Support** - Full export capabilities with detailed metadata

**Example Output:**
```
                             Project Usage Breakdown
┏━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Project   ┃ Sessions ┃ Interactions ┃ Total Tokens ┃    Cost ┃ Models Used     ┃
┡━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ omo-monitor │        5 │           12 │       25,340 │ $0.0512 │ claude-sonnet-… │
│ myapp     │        3 │            8 │       18,200 │ $0.0364 │ claude-opus-4   │
│ website   │        2 │            4 │        8,150 │ $0.0163 │ grok-code       │
└───────────┴──────────┴──────────────┴──────────────┴─────────┴─────────────────┘
╭────────────────────────────────── Summary ───────────────────────────────────╮
│ Total: 3 projects, 10 sessions, 24 interactions, 51,690 tokens, $0.10        │
╰──────────────────────────────────────────────────────────────────────────────╯
```



### 4. Live Monitoring Commands

#### `omo-monitor live <path>`
Real-time monitoring dashboard that updates automatically.

```bash
# Start live monitoring (updates every 5 seconds)
omo-monitor live ~/.local/share/opencode/storage/message

# Custom refresh interval (in seconds)
omo-monitor live ~/.local/share/opencode/storage/message --refresh 10
```

**Features:**
- 🔄 Auto-refreshing display with professional UI redesign
- 📊 Real-time cost tracking with progress indicators  
- ⏱️ Live session duration with 5-hour progress bar and color-coded time alerts
- 📈 Token usage updates and context window monitoring
- 🚦 Color-coded status indicators (green/orange/yellow/red based on time elapsed)
- 📂 Project name display for better context awareness
- 📝 Human-readable session titles replacing cryptic session IDs
- 🎨 Clean, professional styling with optimal space utilization

[![Live Dashboard Screenshot](screenshots/live_dashboard.png)](screenshots/live_dashboard.png)

*Click image to view full-size screenshot of the live monitoring dashboard*

---

## ⚙️ Configuration

### Configuration File Setup

OpenCode Monitor uses a configuration file located at: **`~/.config/omo_monitor/config.toml`**

#### Create Configuration File

```bash
# Create the configuration directory
mkdir -p ~/.config/omo-monitor

# Create your configuration file
touch ~/.config/omo_monitor/config.toml
```

#### Configuration File Search Order

OpenCode Monitor searches for configuration files in this order:
1. **`~/.config/omo_monitor/config.toml`** (recommended user location)
2. `config.toml` (current working directory)
3. `omo-monitor.toml` (current working directory)
4. Project directory fallback

### Setting Custom Message Path

OpenCode Monitor can be configured to use custom paths for your message data.

#### Method 1: Edit Configuration File

Edit your `~/.config/omo_monitor/config.toml` file:

```toml
[paths]
# Custom path to OpenCode messages directory
messages_dir = "/custom/path/to/messages"
# Directory for exports
export_dir = "./my-exports"
```

#### Method 2: Environment Variable

Set the path via environment variable:

```bash
# Set custom path
export OCMONITOR_MESSAGES_DIR="/custom/path/to/messages"

# Use in commands
omo-monitor sessions
```

#### Method 3: Command Line Override

Override the path for individual commands:

```bash
# Use custom path for this command only
omo-monitor sessions /custom/path/to/messages
```

### Full Configuration Options

Here's a complete `~/.config/omo_monitor/config.toml` with all available options:

```toml
# OpenCode Monitor Configuration

[paths]
# Default path to OpenCode messages directory
messages_dir = "~/.local/share/opencode/storage/message"
# Directory for exports
export_dir = "./exports"

[ui]
# Table style: "rich", "simple", "minimal"
table_style = "rich"
# Enable progress bars
progress_bars = true
# Enable colors in output
colors = true
# Refresh interval for live dashboard (seconds)
live_refresh_interval = 5

[export]
# Default export format: "csv", "json"
default_format = "csv"
# Include metadata in exports
include_metadata = true
# Include raw data in exports
include_raw_data = false

[models]
# Path to models pricing configuration
config_file = "models.json"

[analytics]
# Default timeframe for reports: "daily", "weekly", "monthly"
default_timeframe = "daily"
# Number of recent sessions to analyze by default
recent_sessions_limit = 50

[quotas]
# Daily spending limits per model (in USD)
daily_limits = { claude-sonnet-4 = 10.0, claude-opus-4 = 20.0 }
# Monthly spending limits
monthly_limits = { claude-sonnet-4 = 200.0, claude-opus-4 = 400.0 }
# Enable quota warnings
enable_warnings = true
```

---

## 🤖 Adding New Models

### Understanding the Models Configuration

Models are defined in the `models.json` file. Each model includes pricing and technical specifications.

### Current Models Format

```json
{
  "claude-sonnet-4-20250514": {
    "input": 3.0,
    "output": 15.0,
    "cacheWrite": 3.75,
    "cacheRead": 0.30,
    "contextWindow": 200000,
    "sessionQuota": 6.00,
    "description": "Claude Sonnet 4 (2025-05-14)"
  },
  "claude-opus-4": {
    "input": 15.0,
    "output": 75.0,
    "cacheWrite": 18.75,
    "cacheRead": 1.50,
    "contextWindow": 200000,
    "sessionQuota": 10.00,
    "description": "Claude Opus 4"
  },
  "grok-code": {
    "input": 0.0,
    "output": 0.0,
    "cacheWrite": 0.0,
    "cacheRead": 0.0,
    "contextWindow": 256000,
    "sessionQuota": 0.0,
    "description": "Grok Code (Free)"
  }
}
```

### Adding a New Model

#### Step 1: Edit models.json

Add your new model to the `models.json` file:

```json
{
  "existing-models": "...",
  
  "new-ai-model": {
    "input": 5.0,
    "output": 25.0,
    "cacheWrite": 6.25,
    "cacheRead": 0.50,
    "contextWindow": 128000,
    "sessionQuota": 15.0,
    "description": "New AI Model"
  },
  
  "another-model": {
    "input": 0.0,
    "output": 0.0,
    "cacheWrite": 0.0,
    "cacheRead": 0.0,
    "contextWindow": 100000,
    "sessionQuota": 0.0,
    "description": "Another Free Model"
  }
}
```

#### Step 2: Verify the Addition

Test that your new model is recognized:

```bash
# Check if the model appears in configuration
omo-monitor config show

# Test with session data that uses the new model
omo-monitor sessions /path/to/sessions
```

#### Step 3: Handle Fully Qualified Names

For models with provider prefixes (like `provider/model-name`), add both versions:

```json
{
  "provider/model-name": {
    "input": 2.0,
    "output": 10.0,
    "cacheWrite": 2.5,
    "cacheRead": 0.20,
    "contextWindow": 150000,
    "sessionQuota": 8.0,
    "description": "Provider Model"
  },
  "model-name": {
    "input": 2.0,
    "output": 10.0,
    "cacheWrite": 2.5,
    "cacheRead": 0.20,
    "contextWindow": 150000,
    "sessionQuota": 8.0,
    "description": "Provider Model (short name)"
  }
}
```

### Model Configuration Fields

| Field | Description | Required | Example |
|-------|-------------|----------|---------|
| `input` | Cost per 1M input tokens (USD) | ✅ | `3.0` |
| `output` | Cost per 1M output tokens (USD) | ✅ | `15.0` |
| `cacheWrite` | Cost per 1M cache write tokens (USD) | ✅ | `3.75` |
| `cacheRead` | Cost per 1M cache read tokens (USD) | ✅ | `0.30` |
| `contextWindow` | Maximum context window size | ✅ | `200000` |
| `sessionQuota` | Maximum session cost quota (USD) | ✅ | `6.00` |
| `description` | Human-readable model name | ❌ | `"Claude Sonnet 4"` |

### Field Details

- **`input`**: Base cost for processing input tokens (prompt tokens)
- **`output`**: Cost for generating output tokens (response tokens)  
- **`cacheWrite`**: Cost for writing tokens to cache (context caching feature)
- **`cacheRead`**: Cost for reading tokens from cache (much cheaper than input)
- **`contextWindow`**: Maximum number of tokens the model can process in one request
- **`sessionQuota`**: Maximum cost limit per session (0 = no limit)
- **`description`**: Optional human-readable name for display purposes

### Free Models

For free models, set all costs to `0.0`:

```json
{
  "free-model": {
    "input": 0.0,
    "output": 0.0,
    "cacheWrite": 0.0,
    "cacheRead": 0.0,
    "contextWindow": 100000,
    "sessionQuota": 0.0,
    "description": "Free AI Model"
  }
}
```

### Pricing Examples

#### Premium Model (with caching support)
```json
{
  "anthropic.claude-sonnet-4-20250514-v1:0": {
    "input": 3.0,
    "output": 15.0,
    "cacheWrite": 3.75,
    "cacheRead": 0.30,
    "contextWindow": 1000000,
    "sessionQuota": 10.0,
    "description": "Claude Sonnet 4 (2025-05-14)"
  }
}
```

#### Basic Model (no caching)
```json
{
  "gpt-4o": {
    "input": 2.50,
    "output": 10.0,
    "cacheWrite": 0.0,
    "cacheRead": 0.0,
    "contextWindow": 128000,
    "sessionQuota": 0.0,
    "description": "GPT-4o"
  }
}
```

---

## 💰 Setting Usage Quotas

### Understanding Quotas

Quotas help you monitor and control your AI usage costs by setting spending limits.

### Configuring Quotas

#### Method 1: Configuration File

Edit `~/.config/omo_monitor/config.toml` to set quota limits:

```toml
[quotas]
# Daily spending limits per model (in USD)
daily_limits = { 
    claude-sonnet-4 = 10.0, 
    claude-opus-4 = 20.0,
    claude-opus-4.1 = 25.0
}

# Weekly spending limits
weekly_limits = { 
    claude-sonnet-4 = 50.0, 
    claude-opus-4 = 100.0 
}

# Monthly spending limits
monthly_limits = { 
    claude-sonnet-4 = 200.0, 
    claude-opus-4 = 400.0,
    "*" = 500.0  # Total limit across all models
}

# Enable quota warnings
enable_warnings = true

# Warning threshold (percentage of quota)
warning_threshold = 80.0

# Action when quota exceeded: "warn", "block"
quota_action = "warn"
```

#### Method 2: Environment Variables

Set quotas using environment variables:

```bash
# Daily limits
export OCMONITOR_DAILY_CLAUDE_SONNET_4=10.0
export OCMONITOR_DAILY_CLAUDE_OPUS_4=20.0

# Monthly limits
export OCMONITOR_MONTHLY_TOTAL=500.0
```

### Quota Examples

#### Basic Daily Limits

```toml
[quotas]
daily_limits = { 
    claude-sonnet-4 = 15.0,  # $15/day for Sonnet
    claude-opus-4 = 30.0     # $30/day for Opus
}
enable_warnings = true
```

#### Comprehensive Quota Setup

```toml
[quotas]
# Daily limits per model
daily_limits = { 
    claude-sonnet-4 = 10.0,
    claude-opus-4 = 20.0,
    "*" = 35.0  # Total daily limit
}

# Weekly limits
weekly_limits = { 
    claude-sonnet-4 = 60.0,
    claude-opus-4 = 120.0,
    "*" = 200.0
}

# Monthly limits
monthly_limits = { 
    claude-sonnet-4 = 250.0,
    claude-opus-4 = 500.0,
    "*" = 800.0
}

# Warning settings
enable_warnings = true
warning_threshold = 75.0  # Warn at 75% of quota
email_notifications = "admin@example.com"
```

### Viewing Quota Status

Check your current quota usage:

```bash
# Show quota status in daily report
omo-monitor daily ~/.local/share/opencode/storage/message --show-quotas

# Show quota status in model breakdown
omo-monitor models ~/.local/share/opencode/storage/message --show-quotas
```


---

## 📤 Exporting Reports

### Export Command Overview

OpenCode Monitor provides powerful export capabilities for creating reports and integrating with other tools.

### Basic Export Syntax

```bash
omo-monitor export <report_type> [path] [options]
```

### Export Types

#### 1. Sessions Export

Export detailed session data:

```bash
# Export all sessions to CSV
omo-monitor export sessions ~/.local/share/opencode/storage/message --format csv --output sessions_report.csv

# Export to JSON
omo-monitor export sessions ~/.local/share/opencode/storage/message --format json --output sessions_data.json

# Export recent sessions only
omo-monitor export sessions ~/.local/share/opencode/storage/message --limit 50 --format csv
```

#### 2. Daily Reports Export

```bash
# Export daily breakdown
omo-monitor export daily ~/.local/share/opencode/storage/message --format csv --output daily_usage.csv

# Last 30 days
omo-monitor export daily ~/.local/share/opencode/storage/message --days 30 --format json
```

#### 3. Weekly Reports Export

```bash
# Export weekly data
omo-monitor export weekly ~/.local/share/opencode/storage/message --format csv --output weekly_report.csv

# Last 12 weeks
omo-monitor export weekly ~/.local/share/opencode/storage/message --weeks 12 --format json
```

#### 4. Monthly Reports Export

```bash
# Export monthly analysis
omo-monitor export monthly ~/.local/share/opencode/storage/message --format csv --output monthly_analysis.csv

# Last 6 months
omo-monitor export monthly ~/.local/share/opencode/storage/message --months 6 --format json
```

#### 5. Model Usage Export

```bash
# Export model breakdown
omo-monitor export models ~/.local/share/opencode/storage/message --format csv --output model_usage.csv

# JSON format with metadata
omo-monitor export models ~/.local/share/opencode/storage/message --format json --include-metadata
```

#### 6. Project Usage Export

```bash
# Export project breakdown
omo-monitor export projects ~/.local/share/opencode/storage/message --format csv --output project_usage.csv

# JSON format with detailed metadata
omo-monitor export projects ~/.local/share/opencode/storage/message --format json --include-metadata

# Filter by date range
omo-monitor export projects ~/.local/share/opencode/storage/message --start-date 2024-01-01 --end-date 2024-01-31 --format csv
```

### Export Options

| Option | Description | Example |
|--------|-------------|---------|
| `--format` | Output format (`csv`, `json`) | `--format csv` |
| `--output` | Output filename | `--output report.csv` |
| `--limit` | Limit number of records | `--limit 100` |
| `--days` | Number of days to include | `--days 30` |
| `--weeks` | Number of weeks to include | `--weeks 12` |
| `--months` | Number of months to include | `--months 6` |
| `--include-metadata` | Include additional metadata | `--include-metadata` |
| `--include-raw-data` | Include raw session data | `--include-raw-data` |
| `--start-date` | Start date for filtering (YYYY-MM-DD) | `--start-date 2024-01-01` |
| `--end-date` | End date for filtering (YYYY-MM-DD) | `--end-date 2024-01-31` |
| `--timeframe` | Predefined timeframe filter | `--timeframe weekly` |

### CSV Export Example

```bash
omo-monitor export sessions ~/.local/share/opencode/storage/message --format csv --output sessions.csv
```

**Generated CSV Structure:**
```csv
session_id,date,start_time,end_time,duration_minutes,model,total_cost,input_tokens,output_tokens,cache_tokens
ses_20250118_143022,2025-01-18,14:30:22,14:53:37,23.25,claude-sonnet-4,2.45,15420,8340,2100
ses_20250118_120830,2025-01-18,12:08:30,12:53:38,45.13,claude-opus-4,4.32,18650,9240,1850
```

### JSON Export Example

```bash
omo-monitor export sessions ~/.local/share/opencode/storage/message --format json --output sessions.json --include-metadata
```

**Generated JSON Structure:**
```json
{
  "metadata": {
    "export_date": "2025-01-18T15:30:00Z",
    "tool_version": "1.0.0",
    "total_sessions": 25,
    "date_range": {
      "start": "2025-01-01",
      "end": "2025-01-18"
    }
  },
  "sessions": [
    {
      "session_id": "ses_20250118_143022",
      "date": "2025-01-18",
      "start_time": "14:30:22",
      "end_time": "14:53:37",
      "duration_minutes": 23.25,
      "model": "claude-sonnet-4",
      "total_cost": 2.45,
      "tokens": {
        "input": 15420,
        "output": 8340,
        "cache": 2100,
        "total": 25860
      },
      "cost_breakdown": {
        "input_cost": 0.46,
        "output_cost": 1.25,
        "cache_cost": 0.63,
        "total_cost": 2.45
      }
    }
  ]
}
```

### Automated Export Scripts

#### Daily Export Automation

Create a script for daily exports:

```bash
#!/bin/bash
# daily_export.sh

DATE=$(date +%Y%m%d)
EXPORT_DIR="./reports"
MESSAGES_PATH="~/.local/share/opencode/storage/message"

mkdir -p $EXPORT_DIR

# Export daily report
omo-monitor export daily $MESSAGES_PATH \
  --format csv \
  --output "$EXPORT_DIR/daily_${DATE}.csv"

# Export sessions
omo-monitor export sessions $MESSAGES_PATH \
  --format json \
  --output "$EXPORT_DIR/sessions_${DATE}.json" \
  --include-metadata

echo "Reports exported to $EXPORT_DIR/"
```

#### Weekly Report Generation

```bash
#!/bin/bash
# weekly_report.sh

WEEK=$(date +%Y_W%U)
omo-monitor export weekly ~/.local/share/opencode/storage/message \
  --format csv \
  --output "weekly_report_${WEEK}.csv" \
  --weeks 1

omo-monitor export models ~/.local/share/opencode/storage/message \
  --format csv \
  --output "model_usage_${WEEK}.csv"
```

---

## 🔧 Configuration Commands

### `omo-monitor config` Command Reference

The configuration command helps you manage and view your OpenCode Monitor settings.

### Viewing Configuration

#### Show All Configuration

```bash
# Display complete configuration
omo-monitor config show
```


**Text Output Example:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                     ⚙️  Configuration                                        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📁 Paths:
   Messages Directory: ~/.local/share/opencode/storage/message
   Export Directory: ./exports

🎨 UI Settings:
   Table Style: rich
   Progress Bars: enabled
   Colors: enabled
   Live Refresh: 5 seconds

📤 Export Settings:
   Default Format: csv
   Include Metadata: enabled
   Include Raw Data: disabled

🤖 Models:
   Configuration File: models.json
   Supported Models: 6

📊 Analytics:
   Default Timeframe: daily
   Recent Sessions Limit: 50
```

#### Show Specific Configuration Sections

```bash
# Show only paths configuration
omo-monitor config show --section paths

# Show UI settings
omo-monitor config show --section ui

# Show model configuration
omo-monitor config show --section models
```

### Validating Configuration

#### Check Configuration Validity

```bash
# Validate configuration files
omo-monitor config validate
```

**Example Output:**


**Text Output Example:**
```
✅ Configuration validation successful

📋 Validation Results:
   ✅ config.toml: Valid TOML format
   ✅ models.json: Valid JSON format
   ✅ Paths: All directories accessible
   ✅ Models: 6 models configured correctly
   ✅ Quotas: Quota limits properly formatted

🔍 Configuration Details:
   Config File: /path/to/config.toml
   Models File: /path/to/models.json
   Messages Directory: ~/.local/share/opencode/storage/message (exists)
   Export Directory: ./exports (will be created)
```

#### Diagnose Configuration Issues

```bash
# Comprehensive configuration diagnosis
omo-monitor config diagnose
```

**Example Output:**


**Text Output Example:**
```
🔍 Configuration Diagnosis

✅ Configuration Files:
   ✅ config.toml found and valid
   ✅ models.json found and valid

⚠️  Path Issues:
   ⚠️  Messages directory not found: ~/.local/share/opencode/storage/message
   💡 Suggestion: Check if OpenCode is installed and has been run

✅ Model Configuration:
   ✅ 6 models configured
   ✅ All required fields present
   ✅ Valid pricing data

🔧 Recommendations:
   1. Verify OpenCode installation
   2. Run OpenCode at least once to create message directory
   3. Consider setting custom messages_dir if using different location
```

### Updating Configuration

#### Set Configuration Values

```bash
# Set messages directory
omo-monitor config set paths.messages_dir "/custom/path/to/messages"

# Set default export format
omo-monitor config set export.default_format "json"

# Enable/disable UI features
omo-monitor config set ui.colors true
omo-monitor config set ui.progress_bars false

# Set live refresh interval
omo-monitor config set ui.live_refresh_interval 10
```

#### Reset Configuration

```bash
# Reset to default configuration
omo-monitor config reset

# Reset specific section
omo-monitor config reset --section ui

# Backup current config before reset
omo-monitor config reset --backup
```

### Configuration File Locations

#### Find Configuration Files

```bash
# Show configuration file paths
omo-monitor config paths
```

**Example Output:**
```
📁 Configuration File Locations:

Primary Configuration:
   File: ~/.config/omo_monitor/config.toml
   Status: ✅ Found (recommended location)

Project Configuration:
   File: ./config.toml
   Status: ❌ Not found (optional)

Models Configuration:
   File: ./models.json
   Status: ✅ Found

Environment Overrides:
   OCMONITOR_MESSAGES_DIR: not set
   OCMONITOR_EXPORT_DIR: not set
```

### Environment Variable Override

You can override any configuration setting using environment variables:

```bash
# Override messages directory
export OCMONITOR_MESSAGES_DIR="/custom/path"

# Override export format
export OCMONITOR_EXPORT_FORMAT="json"

# Override UI settings
export OCMONITOR_UI_COLORS="false"
export OCMONITOR_UI_TABLE_STYLE="simple"

# Use the overrides
omo-monitor config show
```

---

## 🔧 Troubleshooting

### Common Issues and Solutions

#### 1. Command Not Found: `omo-monitor`

**Problem:** Terminal shows `command not found: omo-monitor`

**Solutions:**

```bash
# Check if Python scripts directory is in PATH
echo $PATH | grep -o '[^:]*python[^:]*bin'

# Find Python user base
python3 -m site --user-base

# Add to PATH (add to ~/.bashrc or ~/.zshrc)
export PATH="$(python3 -m site --user-base)/bin:$PATH"

# Reload shell
source ~/.bashrc  # or ~/.zshrc

# Alternative: Use full path
python3 /path/to/omo_monitor/run_omo-monitor.py --help

# Alternative: Reinstall in development mode
cd /path/to/omo-monitor
python3 -m pip install -e .
```

#### 2. Import Errors and Dependencies

**Problem:** Python import errors when running commands

**Solutions:**

```bash
# Check Python version
python3 --version  # Should be 3.7+

# Reinstall dependencies
python3 -m pip install -r requirements.txt --force-reinstall

# Check for missing dependencies
python3 -c "import click, rich, pydantic, toml; print('All dependencies OK')"

# Install specific missing package
python3 -m pip install click rich pydantic toml

# Clear Python cache
find . -name "__pycache__" -type d -exec rm -rf {} +
find . -name "*.pyc" -delete
```

#### 3. Architecture Compatibility Issues

**Problem:** Architecture mismatch errors (arm64 vs x86_64)

**Solutions:**

```bash
# Check system architecture
uname -m

# For Apple Silicon Macs, use native Python
which python3
/opt/homebrew/bin/python3 --version

# Reinstall with correct architecture
python3 -m pip uninstall pydantic pydantic-core
python3 -m pip install pydantic pydantic-core --no-cache-dir

# Force reinstall all dependencies
python3 -m pip install -r requirements.txt --force-reinstall --no-cache-dir
```

#### 4. Messages Directory Not Found

**Problem:** `Messages directory not found` error

**Solutions:**

```bash
# Check if OpenCode is installed
which opencode

# Check default location
ls -la ~/.local/share/opencode/storage/message

# Find OpenCode data directory
find ~ -name "opencode" -type d 2>/dev/null

# Check OpenCode configuration
opencode config list 2>/dev/null | grep storage

# Set custom path if different location
omo-monitor config set paths.messages_dir "/actual/path/to/messages"

# Verify path is accessible
omo-monitor config validate
```

#### 5. JSON Parsing Errors

**Problem:** Errors when reading session files

**Solutions:**

```bash
# Check for corrupted session files
find ~/.local/share/opencode/storage/message -name "*.json" -exec python3 -m json.tool {} \; > /dev/null

# Find specific problematic files
find ~/.local/share/opencode/storage/message -name "*.json" -print0 | while IFS= read -r -d '' file; do
    python3 -m json.tool "$file" > /dev/null 2>&1 || echo "Invalid JSON: $file"
done

# Test with specific session
omo-monitor session ~/.local/share/opencode/storage/message/problematic_session

# Use verbose mode for debugging
omo-monitor sessions ~/.local/share/opencode/storage/message --verbose
```

#### 6. Permission Errors

**Problem:** Permission denied errors when accessing files

**Solutions:**

```bash
# Check file permissions
ls -la ~/.local/share/opencode/storage/message

# Fix permissions if needed
chmod -R 755 ~/.local/share/opencode/storage/message

# Check if export directory is writable
mkdir -p ./exports
touch ./exports/test.txt && rm ./exports/test.txt

# Use alternative export directory
omo-monitor config set export.export_dir "/tmp/omo-monitor-exports"
```

#### 7. Model Not Recognized

**Problem:** "Unknown model" in reports

**Solutions:**

```bash
# Check which models are configured
omo-monitor config show --section models

# View current models.json
cat models.json

# Find unrecognized model names in your data
grep -r "model.*:" ~/.local/share/opencode/storage/message | grep -v claude | grep -v grok | head -5

# Add missing model to models.json
# Edit models.json and add the new model configuration

# Validate models configuration
omo-monitor config validate
```

#### 8. Export Failures

**Problem:** Export commands fail or produce empty files

**Solutions:**

```bash
# Test export with verbose output
omo-monitor export sessions ~/.local/share/opencode/storage/message --format csv --output test.csv --verbose

# Check export directory permissions
ls -la ./exports

# Try different export format
omo-monitor export sessions ~/.local/share/opencode/storage/message --format json --output test.json

# Test with limited data
omo-monitor export sessions ~/.local/share/opencode/storage/message --limit 5 --format csv

# Check disk space
df -h .
```

### Debug Mode

#### Enable Verbose Logging

```bash
# Run any command with verbose output
omo-monitor sessions ~/.local/share/opencode/storage/message --verbose

# Set debug environment variable
export OCMONITOR_DEBUG=1
omo-monitor sessions ~/.local/share/opencode/storage/message
```

#### Check System Information

```bash
# Show system information for bug reports
omo-monitor config system-info
```


**Text Output Example:**
```
🔍 System Information for Bug Reports

Environment:
   OS: macOS 12.6
   Architecture: arm64
   Python Version: 3.9.16
   OpenCode Monitor Version: 1.0.0

Python Environment:
   Python Path: /opt/homebrew/bin/python3
   Site Packages: /opt/homebrew/lib/python3.9/site-packages
   User Base: /Users/username/Library/Python/3.9

Dependencies:
   ✅ click: 8.1.7
   ✅ rich: 13.7.0
   ✅ pydantic: 2.5.2
   ✅ toml: 0.10.2

Configuration:
   Config File: ./config.toml (exists)
   Models File: ./models.json (exists)
   Messages Dir: ~/.local/share/opencode/storage/message (accessible)

Recent Errors: None
```

### Getting Help

#### Report Issues

When reporting issues, include:

1. **System Information:**
   ```bash
   omo-monitor config system-info
   ```

2. **Error Messages:** Full error output with `--verbose` flag

3. **Configuration:**
   ```bash
   omo-monitor config show
   ```

4. **Steps to Reproduce:** Exact commands that cause the issue

#### Community Support

- 🐛 **GitHub Issues:** For bug reports and feature requests
- 💬 **Discussions:** For questions and community help
- 📚 **Documentation:** Check this guide and README files

---

## 📊 Using the --breakdown Flag

The `--breakdown` flag adds per-model token consumption and cost details to daily, weekly, and monthly reports.

```bash
# Show model breakdown in daily report
omo-monitor daily ~/.local/share/opencode/storage/message --breakdown

# Show model breakdown in weekly report
omo-monitor weekly ~/.local/share/opencode/storage/message --breakdown

# Show model breakdown in monthly report
omo-monitor monthly ~/.local/share/opencode/storage/message --breakdown
```

**Example Output:**
```
                             Daily Usage Breakdown                              
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓
┃ Date / Model                   ┃ Sessions ┃ Interactions┃ Total Tokens┃    Cost ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩
│ 2024-01-13                     │        1 │          2 │     1,150 │ $0.0128 │
│   ↳ claude-sonnet-4-20250514   │        1 │          2 │     1,150 │ $0.0128 │
│ 2024-01-14                     │        1 │          1 │     5,200 │ $0.0000 │
│   ↳ grok-code                  │        1 │          1 │     5,200 │ $0.0000 │
└────────────────────────────────┴──────────┴────────────┴───────────┴─────────┘
```

**Features:**
- Model rows indented and styled distinctly
- Shows sessions, interactions, tokens, and cost per model
- Models sorted by cost (descending)
- Total row shows aggregate values

---

## 🚀 Advanced Tips

### Performance Optimization

#### Large Dataset Handling

```bash
# Process large datasets efficiently
omo-monitor sessions ~/.local/share/opencode/storage/message --limit 1000

# Use JSON format for faster processing
omo-monitor sessions ~/.local/share/opencode/storage/message --format json | jq '.sessions | length'

# Focus on recent data
omo-monitor daily ~/.local/share/opencode/storage/message --days 7
```

#### Batch Processing

```bash
# Process multiple directories
for dir in /path/to/project1/messages /path/to/project2/messages; do
    echo "Processing $dir"
    omo-monitor sessions "$dir" --format csv --output "$(basename $dir)_report.csv"
done
```

### Integration with Other Tools

#### Shell Scripts Integration

```bash
#!/bin/bash
# Monthly cost check script

COST=$(omo-monitor monthly ~/.local/share/opencode/storage/message --format json | jq '.summary.total_cost')
LIMIT=100.0

if (( $(echo "$COST > $LIMIT" | bc -l) )); then
    echo "⚠️ Monthly cost $COST exceeds limit $LIMIT"
    # Send notification, email, etc.
fi
```

#### Data Pipeline Integration

```bash
# Export for data analysis
omo-monitor export sessions ~/.local/share/opencode/storage/message \
    --format json \
    --include-raw-data \
    --output sessions.json

# Export project data for analysis
omo-monitor export projects ~/.local/share/opencode/storage/message \
    --format json \
    --include-metadata \
    --output projects.json

# Process with jq
cat sessions.json | jq '.sessions[] | select(.total_cost > 5.0)'
cat projects.json | jq '.projects[] | select(.cost > 10.0)'

# Import into database (example)
python3 scripts/import_to_db.py sessions.json
python3 scripts/import_projects_to_db.py projects.json
```

### Customization

#### Custom Export Scripts

Create custom export formats:

```python
#!/usr/bin/env python3
# custom_export.py

import json
import sys
from datetime import datetime

def custom_export(sessions_file):
    with open(sessions_file) as f:
        data = json.load(f)
    
    # Custom processing
    for session in data['sessions']:
        print(f"{session['date']},{session['model']},{session['total_cost']}")

if __name__ == "__main__":
    custom_export(sys.argv[1])
```

Usage:
```bash
omo-monitor export sessions ~/.local/share/opencode/storage/message --format json --output temp.json
python3 custom_export.py temp.json > custom_report.csv
```

#### Configuration Templates

Create configuration templates for different use cases:

```bash
# Development configuration
cp ~/.config/omo_monitor/config.toml ~/.config/omo_monitor/config.dev.toml
# Edit development settings
nano ~/.config/omo_monitor/config.dev.toml

# Production configuration  
cp ~/.config/omo_monitor/config.toml ~/.config/omo_monitor/config.prod.toml
# Edit production settings
nano ~/.config/omo_monitor/config.prod.toml

# Use specific configuration
OCMONITOR_CONFIG=~/.config/omo_monitor/config.dev.toml omo-monitor sessions ~/.local/share/opencode/storage/message
```

---

*This completes the comprehensive documentation for OpenCode Monitor. For additional help, please refer to the GitHub repository or file an issue for support.*