#!/bin/bash

# OmO Monitor Installation Script
# This script automates the installation process for OmO Monitor

set -e  # Exit on any error

echo "🚀 OmO Monitor Installation Script"
echo "======================================"

# Check if we're in the right directory
if [ ! -f "setup.py" ] || [ ! -d "omo_monitor" ]; then
    echo "❌ Error: Please run this script from the omo-monitor root directory"
    echo "   The directory should contain setup.py and omo_monitor/ folder"
    exit 1
fi

echo "✅ Found omo_monitor project directory"

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$(printf '%s\n' "3.7" "$PYTHON_VERSION" | sort -V | head -n1)" == "3.7" ]]; then
    echo "✅ Python version $PYTHON_VERSION is supported"
else
    echo "❌ Python 3.7 or higher is required"
    exit 1
fi

# Create virtual environment if it doesn't exist
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "🔨 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Install package in development mode
echo "🔧 Installing omo-monitor in development mode..."
python3 -m pip install -e .

# Get the scripts directory
SCRIPTS_DIR="$(pwd)/$VENV_DIR/bin"
echo "📁 Python scripts installed to: $SCRIPTS_DIR"

# Test installation
echo "🧪 Testing installation..."
if command -v omo-monitor &> /dev/null; then
    echo "✅ omo-monitor command is available"
    omo-monitor --version
else
    echo "⚠️  omo-monitor command not found in PATH"
    echo "   You can run it directly with:"
    echo "   $SCRIPTS_DIR/omo-monitor --help"
fi

echo ""
echo "🎉 Installation complete!"
echo ""
echo "📝 Next steps:"
echo "1. Add $SCRIPTS_DIR to your PATH if you haven't already (see instructions above)"
echo "2. Run 'omo-monitor --help' to see available commands"
echo "3. Run 'omo-monitor config show' to view current configuration"
echo ""
echo "For more detailed usage instructions, see MANUAL_TEST_GUIDE.md"