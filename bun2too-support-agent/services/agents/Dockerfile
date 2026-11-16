FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app/services/agents
COPY services/agents/pyproject.toml services/agents/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/agents ./
COPY tenants /app/tenants
RUN uv sync --frozen --no-dev
ENV RELAY_TENANTS_DIR=/app/tenants RELAY_AGENTS_HOST=0.0.0.0 RELAY_AGENTS_PORT=8080
EXPOSE 8080
CMD ["uv", "run", "--no-dev", "python", "-m", "relay_agents"]
