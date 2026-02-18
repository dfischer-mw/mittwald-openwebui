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
- GitLab: `.gitlab-ci.yml`

## Published image

- `ghcr.io/mittwald/openwebui:latest`
- `ghcr.io/mittwald/openwebui:<open-webui-version>`
- `ghcr.io/mittwald/openwebui:<open-webui-version>-<yyyymmdd>`

## Links

- Package: https://github.com/orgs/mittwald/packages/container/package/openwebui
- Registry API (example tag): `https://ghcr.io/v2/mittwald/openwebui/manifests/<tag>`

## Required variables

### GitHub

- Built-in `GITHUB_TOKEN` with package write permission

### GitLab

- `GHCR_USERNAME`
- `GHCR_TOKEN`
- Optional: `MITTWALD_API_TOKEN`, `OWUI_VERSION`, `PUSH_IMAGE`
