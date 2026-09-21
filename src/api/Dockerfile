FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.12-slim AS build
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src/api ./src/api
COPY src/contracts ./src/contracts
COPY src/gateway ./src/gateway
RUN uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.12-slim
RUN groupadd --gid 10001 innexq && useradd --uid 10001 --gid innexq --no-create-home innexq
WORKDIR /app
COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 corpus ./corpus
COPY --chown=10001:10001 docs/security/certificate-release-policy-v1.md ./docs/security/certificate-release-policy-v1.md
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "innexq_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
