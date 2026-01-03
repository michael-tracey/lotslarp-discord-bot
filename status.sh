#!/bin/bash

# Wrapper script to run the Python status report using uv for dependency management

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Error: 'uv' is required but not installed."
    echo "Please install it: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run with ephemeral dependencies
uv run \
    --with google-cloud-billing \
    --with google-cloud-firestore \
    --with google-cloud-monitoring \
    "$SCRIPT_DIR/scripts/status/system_report.py"