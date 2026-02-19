ARG OWUI_VERSION=latest
FROM ghcr.io/open-webui/open-webui:${OWUI_VERSION}

LABEL org.opencontainers.image.title="mittwald/openwebui" \
      org.opencontainers.image.description="Mittwald-hardened Open WebUI image with dynamic model discovery/bootstrap" \
      org.opencontainers.image.vendor="Mittwald" \
      org.opencontainers.image.licenses="BSD-3-Clause"

# Copy bootstrap scripts
COPY bootstrap/start-with-bootstrap.sh /usr/local/bin/start-with-bootstrap.sh
COPY bootstrap/seed_user_chat_params_once.py /usr/local/bin/seed_user_chat_params_once.py
COPY bootstrap/seed_mittwald_openai_config.py /usr/local/bin/seed_mittwald_openai_config.py
COPY bootstrap/patch_openwebui_source.py /usr/local/bin/patch_openwebui_source.py
COPY bootstrap/hf-model-hyperparameters.json /usr/local/share/openwebui/hf-model-hyperparameters.json

RUN chmod 755 /usr/local/bin/start-with-bootstrap.sh /usr/local/bin/seed_user_chat_params_once.py /usr/local/bin/seed_mittwald_openai_config.py /usr/local/bin/patch_openwebui_source.py \
  && python3 /usr/local/bin/patch_openwebui_source.py

# Set default environment variables for bootstrap
ENV OWUI_DB_PATH="/app/backend/data/webui.db"
ENV OWUI_BOOTSTRAP_MARKER="/app/backend/data/.bootstrapped_chat_params"
ENV OWUI_BOOTSTRAP_REAPPLY_ON_START="false"
ENV MITTWALD_OPENAI_BASE_URL="https://llm.aihosting.mittwald.de/v1"
ENV HF_MODEL_HYPERPARAMS_PATH="/usr/local/share/openwebui/hf-model-hyperparameters.json"

# Expose default port
EXPOSE 8080

# Explicit health check for orchestrators.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=10 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/liveness', timeout=5)"

# Run our wrapper instead of the stock CMD
CMD ["bash", "/usr/local/bin/start-with-bootstrap.sh"]
