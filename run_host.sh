#!/bin/bash
# Quick start script for UniCent HOST
# Usage: sudo ./run_host.sh [options]
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 -m host.main "$@"
