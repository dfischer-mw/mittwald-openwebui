# Setup Guide

## 1. GitHub Actions setup

The workflow uses GHCR and pushes `ghcr.io/mittwald/openwebui`.

### Required

- Repository Actions permissions must allow package write for workflows.

### Optional secrets

- `MITTWALD_API_TOKEN`
- `HUGGINGFACE_TOKEN`

### Run manually

1. Open Actions
2. Select `Build and Publish mittwald/openwebui`
3. Click `Run workflow`
4. Optional inputs:
   - `owui_version`
   - `push_image`

## 2. GitLab CI setup

Create these CI/CD variables:

- `GHCR_USERNAME` (required for publishing)
- `GHCR_TOKEN` (required for publishing)
- `MITTWALD_API_TOKEN` (optional)
- `OWUI_VERSION` (optional override)
- `PUSH_IMAGE=false` (optional test-only mode)

The pipeline file is `.gitlab-ci.yml`.

### GitLab schedule

Create a scheduled pipeline in GitLab UI targeting the default branch (daily recommended).

## 3. Verify output links

After successful CI run:

- Package page: https://github.com/orgs/mittwald/packages/container/package/openwebui
- Pull example:

```bash
docker pull ghcr.io/mittwald/openwebui:<tag>
```
