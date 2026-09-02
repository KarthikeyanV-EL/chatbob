FROM python:3.12-slim

LABEL maintainer="ChatBob" \
      description="ChatGPT-style web UI for IBM Bob (Python backend)"

# Install curl, bash, and Node.js 22.x (required by the Bob Shell installer)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      bash \
      ca-certificates \
      gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install IBM Bob Shell via the official installer
RUN curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash

# Install fetch-mcp globally — gives Bob a tool to fetch and read any URL
RUN npm install -g fetch-mcp

# Ensure bob and npm global bins are on PATH
ENV PATH="/root/.local/bin:/usr/local/bin:${PATH}"

# App directory
WORKDIR /app

# Copy application files (server + static UI + entrypoint)
COPY server.py      ./
COPY public/        ./public/
COPY entrypoint.sh  ./entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# config.json is optional — secrets should come via env vars, not baked into image.
# Mount at runtime:  -v $(pwd)/config.json:/app/config.json:ro
# Or pass directly:  -e BOB_API_KEY=...

# Expose default port (override with -e PORT=xxxx)
ENV PORT=3000
EXPOSE 3000

# Health check — lightweight GET on /api/config
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/api/config')" || exit 1

# Entrypoint writes the MCP config then starts the Python server
CMD ["/app/entrypoint.sh"]
