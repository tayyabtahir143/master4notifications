#!/usr/bin/env bash
PYTHONPATH="$(dirname "$0")/../src" exec python3 "$(dirname "$0")/../src/gui.py" "$@"
