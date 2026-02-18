# mittwald/openwebui CI Build System

This repository builds and publishes a patched Open WebUI image to GitHub Container Registry as:

- `ghcr.io/<repo-owner>/<repo-name>:<open-webui-version>-<yyyymmdd>`
- `ghcr.io/<repo-owner>/<repo-name>:<open-webui-version>`
- `ghcr.io/<repo-owner>/<repo-name>:latest`

Package link:
- `https://github.com/users/<repo-owner>/packages/container/package/<repo-name>`
- `https://github.com/orgs/<repo-owner>/packages/container/package/<repo-name>`

Override target image name with repository variable `GHCR_IMAGE_NAME` if needed.

## What is implemented

- Daily build on GitHub Actions (`.github/workflows/openwebui-monitor.yml`)
- Push-triggered build on GitHub Actions (`main` branch)
- Stable Open WebUI release auto-resolution (or manual override)
- Automatic publish of `:latest` on every successful push/scheduled run
- Hugging Face settings scrape (`scripts/scrape_huggingface.py`)
- Mittwald model scrape (`scripts/scrape_mittwald_portal.py`, optional token)
- Bootstrap seeding in container startup:
  - One-time user chat defaults
  - Mittwald OpenAI provider auto-configuration
  - Auto-discovery of all available Mittwald models from `/v1/models` (including embeddings and Whisper)
  - Auto-setup of Open WebUI STT engine for Mittwald Whisper model
- Full CI test flow:
  - Python compile checks
  - Python unit tests for all custom Python scripts
  - Container integration tests via `scripts/test_image.sh`

## CI files

- GitHub: `.github/workflows/openwebui-monitor.yml`

## Required credentials

### GitHub Actions

No Docker Hub credentials are needed.

- `GITHUB_TOKEN` is used automatically to push to GHCR.
- Optional: `MITTWALD_API_TOKEN` and `HUGGINGFACE_TOKEN`

## GitHub behavior

- Push trigger on `main`
- Scheduled daily at `02:17 UTC`
- Manual dispatch supports:
  - `owui_version`
  - `push_image`
- Summary includes image tags and direct links

## Local development

```bash
make build
make test
make check
make test-full
```

## Mittwald-ready runtime

Run the image with Mittwald API key and it will auto-configure Open WebUI on startup:

- Discovers model IDs from `GET /v1/models`
- Injects model list into OpenAI-compatible provider config
- Sets default chat model
- Sets RAG embedding engine/model when an embedding model is available
- Sets STT engine to `openai` and selects a Whisper model automatically

```bash
docker run -d -p 3000:8080 \\
  -v open-webui-data:/app/backend/data \\
  -e MITTWALD_OPENAI_API_KEY=sk-... \\
  -e MITTWALD_OPENAI_BASE_URL=https://llm.aihosting.mittwald.de/v1 \\
  ghcr.io/<repo-owner>/<repo-name>:latest
```

## Local image push to GHCR

```bash
make build
GHCR_USERNAME=<user> GHCR_TOKEN=<token> make push
```

## Bootstrap env vars

- `OWUI_BOOTSTRAP_TEMPERATURE`
- `OWUI_BOOTSTRAP_TOP_P`
- `OWUI_BOOTSTRAP_TOP_K`
- `OWUI_BOOTSTRAP_REPETITION_PENALTY`
- `OWUI_BOOTSTRAP_MAX_TOKENS`
- `OWUI_DB_PATH`
- `OWUI_BOOTSTRAP_MARKER`
- `MITTWALD_OPENAI_API_KEY`
- `MITTWALD_OPENAI_BASE_URL` (default: `https://llm.aihosting.mittwald.de/v1`)
- `MITTWALD_CONFIGURE_AUDIO_STT` (default: `true`)
- `MITTWALD_DISCOVERY_TIMEOUT_SEC` (default: `20`)

## Testing scope

Unit tests cover all custom Python modules:

- `bootstrap/seed_user_chat_params_once.py`
- `bootstrap/seed_mittwald_openai_config.py`
- `scripts/scrape_huggingface.py`
- `scripts/scrape_mittwald_portal.py`

Container tests validate image startup, bootstrap presence, health endpoint, restart behavior, and data path access.
