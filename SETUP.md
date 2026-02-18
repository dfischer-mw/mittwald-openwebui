# Setup Guide

## 1. GitHub Actions setup

The workflow uses GHCR and pushes to `ghcr.io/<repo-owner>/openwebui` by default.
Every successful publish pushes three tags: `<version>-<date>`, `<version>`, and `latest`.

### Required

- Repository Actions permissions must allow package write for workflows.

### Optional secrets

- `MITTWALD_API_TOKEN`
- `HUGGINGFACE_TOKEN`

### Runtime secret (container)

- `MITTWALD_OPENAI_API_KEY` for automatic Mittwald model discovery and provider setup in Open WebUI.

### Run manually

1. Open Actions
2. Select `Build and Publish mittwald/openwebui`
3. Click `Run workflow`
4. Optional inputs:
   - `owui_version`
   - `push_image`

## 2. Verify output links

After successful CI run:

- Package page:
  - `https://github.com/users/<repo-owner>/packages/container/package/openwebui`
  - `https://github.com/orgs/<repo-owner>/packages/container/package/openwebui`
- Pull example:

```bash
docker pull ghcr.io/<repo-owner>/openwebui:<tag>
```
