# Imagen base con Python 3.12
FROM python:3.12-slim

# Instalar uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Primero solo dependencias (aprovecha caché)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Después el código
COPY app ./app

# Variables por defecto (se sobreescriben por el host)
ENV DATABASE_URL=sqlite:///./pricetracker.db \
    ENABLE_SCANNER=1 \
    SCAN_INTERVAL_MINUTES=60

EXPOSE 8000

# Activa el venv de uv y corre uvicorn
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]