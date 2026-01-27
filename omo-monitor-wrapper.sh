#!/bin/bash
# OmO Monitor Global Wrapper Script
# This script allows omo-monitor to be run from anywhere without activating the virtual environment

# Get the directory where this script is located (the project directory)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Path to the virtual environment's omo-monitor
OMO_MONITOR_SCRIPT="$PROJECT_DIR/venv/bin/omo-monitor"

# Check if omo-monitor exists
if [ ! -f "$OMO_MONITOR_SCRIPT" ]; then
    echo "Error: omo-monitor not found at $OMO_MONITOR_SCRIPT"
    echo "Please run install.sh from the project directory"
    exit 1
fi

# Execute omo-monitor with all arguments passed to this script
exec "$OMO_MONITOR_SCRIPT" "$@"
