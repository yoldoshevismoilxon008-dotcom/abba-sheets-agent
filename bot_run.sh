#!/bin/bash
# Q&A bot listener wrapper — launchd (com.abba.sheets-bot) shu skriptni ishga tushiradi.
cd "$(dirname "$0")"
export PATH="$HOME/.claude/local:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONWARNINGS="ignore"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
exec venv/bin/python -u bot_listener.py
