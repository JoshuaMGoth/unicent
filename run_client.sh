#!/bin/bash
# Quick start script for UniCent CLIENT
# Usage: ./run_client.sh [options]
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 -m client.main "$@"
