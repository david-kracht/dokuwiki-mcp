FROM python:3.12-slim

WORKDIR /app

# System-Abhängigkeiten updaten und NodeJS installieren (für den MCP Inspector)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv installieren (das superschnelle Build-Tool)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# WICHTIG: README.md muss mitkopiert werden, da pyproject.toml sie referenziert!
COPY pyproject.toml README.md ./
COPY src/ src/

# Virtuelles Environment erstellen und Abhängigkeiten installieren
RUN uv venv /app/.venv
RUN uv pip install -e .

# Wir fügen das .venv in den PATH ein
ENV PATH="/app/.venv/bin:$PATH"

# Ports freigeben: 8000 für SSE API, 5173 für den Web Inspector
EXPOSE 8000 5173

CMD ["python", "-m", "src.dokuwiki_mcp.server"]