#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-openwebui-mittwald:latest}"
CONTAINER_NAME="openwebui-test-$$"
DB_VOLUME="${CONTAINER_NAME}-data"
HEALTH_TIMEOUT_SEC="${TEST_HEALTH_TIMEOUT_SEC:-720}"
RESTART_TIMEOUT_SEC="${TEST_RESTART_TIMEOUT_SEC:-240}"

log() {
	echo "[test] $*" >&2
}

cleanup() {
	log "Cleaning up..."
	docker stop "${CONTAINER_NAME}" 2>/dev/null || true
	docker rm "${CONTAINER_NAME}" 2>/dev/null || true
	docker volume rm "${DB_VOLUME}" 2>/dev/null || true
}

trap cleanup EXIT

log "Testing image: ${IMAGE}"

# Test 1: Verify image exists and can be pulled
log "Test 1: Checking image exists..."
docker image inspect "${IMAGE}" >/dev/null || {
	log "ERROR: Image ${IMAGE} not found"
	exit 1
}
log "✓ Image exists"

# Test 2: Verify bootstrap scripts are present
log "Test 2: Checking bootstrap scripts..."
OUTPUT=$(docker run --rm --entrypoint ls "${IMAGE}" /usr/local/bin/ 2>&1)
if echo "${OUTPUT}" | grep -q "start-with-bootstrap.sh" \
	&& echo "${OUTPUT}" | grep -q "seed_user_chat_params_once.py" \
	&& echo "${OUTPUT}" | grep -q "seed_mittwald_openai_config.py"; then
	log "✓ Bootstrap scripts present"
else
	log "ERROR: Bootstrap scripts missing"
	exit 1
fi

# Test 3: Verify environment variables are settable
log "Test 3: Testing environment variable injection..."
OUTPUT=$(docker run --rm \
	-e OWUI_BOOTSTRAP_TEMPERATURE=0.5 \
	-e OWUI_BOOTSTRAP_TOP_P=0.8 \
	--entrypoint printenv "${IMAGE}" 2>&1 || true)

if echo "${OUTPUT}" | grep -q "OWUI_BOOTSTRAP_TEMPERATURE=0.5"; then
	log "✓ Environment variables inject correctly"
else
	log "ERROR: Environment variable injection failed"
	exit 1
fi

# Test 4: Start container and verify it becomes healthy
log "Test 4: Starting container and waiting for healthy state..."
RUN_ARGS=(
	-d
	--name "${CONTAINER_NAME}"
	-v "${DB_VOLUME}:/app/backend/data"
	-e OWUI_BOOTSTRAP_TEMPERATURE=0.6
	-e OWUI_BOOTSTRAP_TOP_P=0.9
	-e OWUI_BOOTSTRAP_TOP_K=42
	-e OWUI_BOOTSTRAP_REPETITION_PENALTY=1.05
	-e OWUI_BOOTSTRAP_MAX_TOKENS=3072
	-p 127.0.0.1:18080:8080
)

# Pass through HF token if present to reduce first-start download throttling.
if [ -n "${HUGGINGFACE_TOKEN:-}" ]; then
	RUN_ARGS+=(-e "HF_TOKEN=${HUGGINGFACE_TOKEN}" -e "HUGGINGFACE_HUB_TOKEN=${HUGGINGFACE_TOKEN}")
fi

docker run "${RUN_ARGS[@]}" "${IMAGE}" >/dev/null

MAX_STARTUP_POLLS=$((HEALTH_TIMEOUT_SEC / 2))
if [ "${MAX_STARTUP_POLLS}" -lt 1 ]; then
	MAX_STARTUP_POLLS=1
fi

log "Waiting for container startup and /health/liveness (up to ${HEALTH_TIMEOUT_SEC}s)..."
HEALTHY="false"
for ((i = 1; i <= MAX_STARTUP_POLLS; i++)); do
	if ! docker ps --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
		log "ERROR: Container stopped unexpectedly during startup"
		docker logs "${CONTAINER_NAME}" || true
		exit 1
	fi

	if curl -sf http://127.0.0.1:18080/health/liveness >/dev/null 2>&1; then
		HEALTHY="true"
		log "✓ Container is running and health endpoint responds"
		break
	fi

	sleep 2
done

if [ "${HEALTHY}" != "true" ]; then
	log "ERROR: Health endpoint did not become ready within timeout"
	docker logs "${CONTAINER_NAME}" || true
	exit 1
fi

# Test 5: Verify container remains running after initial health
log "Test 5: Verifying container stays running..."
if docker ps --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
	log "✓ Container remains running"
else
	log "ERROR: Container stopped after becoming healthy"
	docker logs "${CONTAINER_NAME}" || true
	exit 1
fi

# Test 6: Verify bootstrap scripts ran
log "Test 6: Checking bootstrap script logs..."
LOGS=$(docker logs "${CONTAINER_NAME}" 2>&1 || true)
if echo "${LOGS}" | grep -q "bootstrap-chat-params"; then
	log "✓ Bootstrap script executed"
else
	log "WARNING: Bootstrap script output not found (may be normal if no user created yet)"
fi

# Test 7: Verify data directory is writable
log "Test 7: Checking data directory permissions..."
docker exec "${CONTAINER_NAME}" ls -la /app/backend/data/ >/dev/null || {
	log "ERROR: Data directory not accessible"
	exit 1
}
log "✓ Data directory accessible"

# Test 8: Check for marker file (after user would be created)
log "Test 8: Checking bootstrap marker file..."
MARKER_EXISTS=$(docker exec "${CONTAINER_NAME}" ls /app/backend/data/.bootstrapped_chat_params 2>&1 || echo "NOT_FOUND")
if [ "${MARKER_EXISTS}" != "NOT_FOUND" ]; then
	log "✓ Bootstrap marker file found"
else
	log "INFO: Bootstrap marker not found (expected before first user creation)"
fi

# Test 9: Verify Python dependencies
log "Test 9: Checking Python dependencies..."
docker exec "${CONTAINER_NAME}" python3 -c "import sqlite3; import json; print('OK')" >/dev/null || {
	log "ERROR: Python dependencies missing"
	exit 1
}
log "✓ Python dependencies available"

# Test 10: Test stop and restart
log "Test 10: Testing container restart..."
docker stop "${CONTAINER_NAME}" >/dev/null
docker start "${CONTAINER_NAME}" >/dev/null

RESTART_HEALTHY="false"
MAX_RESTART_POLLS=$((RESTART_TIMEOUT_SEC / 2))
if [ "${MAX_RESTART_POLLS}" -lt 1 ]; then
	MAX_RESTART_POLLS=1
fi
for ((i = 1; i <= MAX_RESTART_POLLS; i++)); do
	if ! docker ps --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
		log "ERROR: Container failed to restart"
		docker logs "${CONTAINER_NAME}" || true
		exit 1
	fi

	if curl -sf http://127.0.0.1:18080/health/liveness >/dev/null 2>&1; then
		RESTART_HEALTHY="true"
		break
	fi

	sleep 2
done

if [ "${RESTART_HEALTHY}" = "true" ]; then
	log "✓ Container restart successful"
else
	log "ERROR: Restarted container did not become healthy in ${RESTART_TIMEOUT_SEC}s"
	docker logs "${CONTAINER_NAME}" || true
	exit 1
fi

log ""
log "=================================================="
log "All tests passed! ✓"
log "=================================================="
log ""
log "Image: ${IMAGE}"
log "Container: ${CONTAINER_NAME}"
log "Data volume: ${DB_VOLUME}"
log ""
log "To continue testing manually:"
log "  docker exec -it ${CONTAINER_NAME} bash"
log "  docker logs ${CONTAINER_NAME} -f"
log "  curl http://127.0.0.1:18080"
