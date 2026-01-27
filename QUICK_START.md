# 🚀 Quick Start Guide

Get up and running with OpenCode Monitor in just a few minutes!

## 📋 Prerequisites

- Python 3.7 or higher
- pip package manager
- OpenCode session data (stored in `~/.local/share/opencode/storage/message/`)

## 🛠️ Installation

### Option 1: Automated Installation (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd omo-monitor

# Run the installation script
./install.sh
```

### Option 2: Manual Installation

```bash
# Clone the repository
git clone <repository-url>
cd omo-monitor

# Install dependencies
python3 -m pip install -r requirements.txt

# Install the package
python3 -m pip install -e .

# Add to PATH (if needed)
echo 'export PATH="$(python3 -m site --user-base)/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## 🎯 First Steps

### 1. Check Configuration
```bash
omo-monitor config show
```

### 2. Analyze Your Sessions
```bash
# Analyze all sessions (uses default OpenCode directory)
omo-monitor sessions

# Analyze a specific session
omo-monitor session /path/to/specific/session
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

### 4. Export Data
```bash
# Export to CSV
omo-monitor export sessions --format csv --output my_report.csv

# Export to JSON
omo-monitor export sessions --format json --output my_report.json
```

### 5. Real-time Monitoring
```bash
# Start live dashboard
omo-monitor live
```

## 📖 Common Commands

| Command | Description |
|---------|-------------|
| `omo-monitor --help` | Show all available commands |
| `omo-monitor config show` | Display current configuration |
| `omo-monitor sessions` | Analyze all sessions |
| `omo-monitor session <path>` | Analyze a single session |
| `omo-monitor daily` | Daily usage breakdown |
| `omo-monitor models` | Model usage analytics |
| `omo-monitor live` | Real-time monitoring dashboard |
| `omo-monitor export <type> --format <csv/json>` | Export data |

## 🎨 Output Formats

All commands support different output formats:

```bash
# Rich tables (default)
omo-monitor sessions

# JSON output
omo-monitor sessions --format json

# Export to files
omo-monitor export sessions --format csv --output report.csv
```

## 🤔 Need Help?

- Run `omo-monitor <command> --help` for specific command help
- Check `MANUAL_TEST_GUIDE.md` for comprehensive usage examples
- File an issue on GitHub if you encounter problems

## 🎉 You're Ready!

Start exploring your OpenCode session data and gain insights into your AI-assisted coding patterns!