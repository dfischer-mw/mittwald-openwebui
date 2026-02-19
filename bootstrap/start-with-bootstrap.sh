#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[bootstrap-entrypoint] $*" >&2
}

# Sync Mittwald OpenAI provider config into Open WebUI config (safe no-op without API key).
if ! python3 /usr/local/bin/seed_mittwald_openai_config.py; then
  if [ "${MITTWALD_FAIL_FAST:-false}" = "true" ]; then
    log "Mittwald bootstrap failed and MITTWALD_FAIL_FAST=true; aborting container startup."
    exit 1
  fi
  log "Mittwald bootstrap failed; continuing startup (MITTWALD_FAIL_FAST=false)."
fi

# Fast synchronous pass for existing users/chats so defaults are already correct
# right after container restart. Keep timeouts very short to avoid blocking first boot.
OWUI_BOOTSTRAP_DB_WAIT_TIMEOUT_SEC="${OWUI_BOOTSTRAP_DB_WAIT_TIMEOUT_SEC:-3}" \
OWUI_BOOTSTRAP_MAX_WAIT_SECONDS="${OWUI_BOOTSTRAP_STARTUP_MAX_WAIT_SECONDS:-3}" \
python3 /usr/local/bin/seed_user_chat_params_once.py || true

# Background pass for first-signup scenarios (fresh volume / no user yet).
python3 /usr/local/bin/seed_user_chat_params_once.py &

# Keep the original behavior as PID1 (signal handling stays correct)
exec bash /app/backend/start.sh
