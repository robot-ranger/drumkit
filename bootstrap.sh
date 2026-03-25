#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
REQ_FILE="requirements.txt"

SYS_PACKAGES=(
  libasound2-dev
  python3-dev
  python3-venv
  swig
  build-essential
  liblgpio-dev
)

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not installed."
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Error: apt-get not found. This script currently supports Debian/Ubuntu systems."
  exit 1
fi

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y "${SYS_PACKAGES[@]}"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
else
  echo "Virtual environment already exists at $VENV_DIR. Skipping creation."
fi

echo "Installing Python dependencies into $VENV_DIR..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r "$REQ_FILE"

echo "Bootstrap complete."
echo "Activate with: source $VENV_DIR/bin/activate"
