# Wave Fixture AI — MCP server (stdio transport)
# Build:  docker build -t wave-fixture-ai-mcp .
# Run:    docker run -i --rm wave-fixture-ai-mcp
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg

WORKDIR /app
COPY . /app
RUN pip install /app \
    && useradd --create-home --uid 10001 mcp

USER mcp
WORKDIR /home/mcp

ENTRYPOINT ["wave-fixture-ai-mcp"]
