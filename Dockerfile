FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        fonts-dejavu-core \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md requirements.txt /app/
COPY src /app/src
COPY scripts /app/scripts
COPY config /app/config
COPY imagenes_ig /app/imagenes_ig
COPY web /app/web

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

CMD ["python", "scripts/check_automation_readiness.py"]
