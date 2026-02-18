# Quick Reference

## Local

```bash
make build
make test
make check
make test-full
```

## Publish local build to GHCR

```bash
GHCR_USERNAME=<user> GHCR_TOKEN=<token> make push
```

## CI files

- GitHub: `.github/workflows/openwebui-monitor.yml`

## Published image

- `ghcr.io/<repo-owner>/<repo-name>:latest`
- `ghcr.io/<repo-owner>/<repo-name>:<open-webui-version>`
- `ghcr.io/<repo-owner>/<repo-name>:<open-webui-version>-<yyyymmdd>`

## Links

- Package:
  - `https://github.com/users/<repo-owner>/packages/container/package/<repo-name>`
  - `https://github.com/orgs/<repo-owner>/packages/container/package/<repo-name>`
- Registry API (example tag): `https://ghcr.io/v2/<repo-owner>/<repo-name>/manifests/<tag>`

## Required variables

### GitHub

- Built-in `GITHUB_TOKEN` with package write permission

### Runtime (Container)

- `MITTWALD_OPENAI_API_KEY` to auto-discover and inject Mittwald models into Open WebUI
- Optional: `MITTWALD_OPENAI_BASE_URL` (default: `https://llm.aihosting.mittwald.de/v1`)
- Optional toggles:
  - `MITTWALD_CONFIGURE_AUDIO_STT=true`
  - `MITTWALD_SET_DEFAULT_MODEL=true`
  - `MITTWALD_CONFIGURE_RAG_EMBEDDING=true`
