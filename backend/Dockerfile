# syntax=docker/dockerfile:1

# ---- Stage 1: build the virtual environment --------------------------------
FROM python:3.13-slim AS builder

# Pin uv to the same version that builds the project (see [build-system]).
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 1) Dependencies only. This layer is cached until pyproject.toml/uv.lock change,
#    so editing code doesn't reinstall every package.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# 2) Our own package, installed as a normal (non-editable) package.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


# ---- Stage 2: the small runtime image ---------------------------------------
# Same base image as the builder, so the venv's Python path still works.
FROM python:3.13-slim

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

CMD ["uvicorn", "lock_in_mode_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
