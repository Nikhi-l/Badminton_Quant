#!/usr/bin/env bash
# Repo check gate (pragmatic harness). Run before marking a task done.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python

echo "==> byte-compiling app/"
"$PY" -m compileall -q app

echo "==> running tests"
"$PY" -m pytest tests -q

echo "OK"
