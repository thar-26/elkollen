# Backend for the public demo: the HTTP API (public) and the MCP server (internal only)
# in one container. Built and run by Render (render.yaml); runs the same locally:
#   docker build -t elkollen-api .
#   docker run --env-file .env -p 10000:10000 elkollen-api
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies pinned by requirements-lock.txt; no dbt or dev tools at runtime.
COPY pyproject.toml requirements-lock.txt README.md ./
COPY src ./src
RUN pip install -c requirements-lock.txt ".[api,forecast]" snowflake-connector-python

COPY reports ./reports
COPY deploy/start-backend.sh ./deploy/start-backend.sh

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# The MCP server listens on localhost only; only the API is reachable from outside.
ENV ELKOLLEN_MCP_HOST=127.0.0.1 \
    ELKOLLEN_MCP_PORT=8001 \
    ELKOLLEN_MCP_URL=http://127.0.0.1:8001/mcp \
    PORT=10000
EXPOSE 10000

CMD ["bash", "deploy/start-backend.sh"]
