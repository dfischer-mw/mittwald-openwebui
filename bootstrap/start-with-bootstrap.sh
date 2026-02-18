#!/usr/bin/env bash
set -euo pipefail

# Sync Mittwald OpenAI provider config into Open WebUI config (safe no-op without API key).
python3 /usr/local/bin/seed_mittwald_openai_config.py || true

# Fire-and-forget bootstrap (runs once per volume)
python3 /usr/local/bin/seed_user_chat_params_once.py &

# Keep the original behavior as PID1 (signal handling stays correct)
exec bash /app/backend/start.sh
