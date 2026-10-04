# Multi-stage build: dependencies are resolved into a venv in the builder, and
# the runtime image carries only that venv plus the source — no build toolchain,
# no uv, no package cache.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-compile .

FROM python:3.12-slim AS runtime

# Unbuffered output so logs appear in `docker logs` as they happen.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv

USER app
WORKDIR /app

# The server binds to 127.0.0.1 by default (ADR 8), which is unreachable from
# outside a container. Docker deployments must set HOST=0.0.0.0 explicitly —
# see the README. Overriding it here would defeat that default.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(s.connect_ex(('127.0.0.1', 8000)))"

ENTRYPOINT ["telegraph-mcp"]
CMD ["serve"]