#!/usr/bin/env bash
set -euo pipefail

# Fire-and-forget bootstrap (runs once per volume)
python3 /usr/local/bin/seed_user_chat_params_once.py &

# Keep the original behavior as PID1 (signal handling stays correct)
exec bash /app/backend/start.sh
