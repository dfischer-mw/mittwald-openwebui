ARG OWUI_VERSION=latest
FROM ghcr.io/open-webui/open-webui:${OWUI_VERSION}

# Copy bootstrap scripts
COPY bootstrap/start-with-bootstrap.sh /usr/local/bin/start-with-bootstrap.sh
COPY bootstrap/seed_user_chat_params_once.py /usr/local/bin/seed_user_chat_params_once.py

RUN chmod 755 /usr/local/bin/start-with-bootstrap.sh /usr/local/bin/seed_user_chat_params_once.py

# Set default environment variables for bootstrap
ENV OWUI_DB_PATH="/app/backend/data/webui.db"
ENV OWUI_BOOTSTRAP_MARKER="/app/backend/data/.bootstrapped_chat_params"

# Expose default port
EXPOSE 8080

# Run our wrapper instead of the stock CMD
CMD ["bash", "/usr/local/bin/start-with-bootstrap.sh"]
