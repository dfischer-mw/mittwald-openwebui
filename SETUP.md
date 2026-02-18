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

## 2. Verify output links

After successful CI run:

- Package page: https://github.com/orgs/mittwald/packages/container/package/openwebui
- Pull example:

```bash
docker pull ghcr.io/mittwald/openwebui:<tag>
```
