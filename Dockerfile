# Codex Cartographer — public web demo (Render / Railway / HF Spaces / any Docker host)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CODEX_WORK_DIR=/tmp/codex_jobs \
    PORT=7860

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-web.txt pyproject.toml README.md ./
COPY codex_cartographer ./codex_cartographer
COPY webapp ./webapp
COPY samples ./samples

RUN pip install --upgrade pip \
    && pip install -r requirements.txt -r requirements-web.txt \
    && pip install -e .

EXPOSE 7860

# HF Spaces expects 7860; Render/Railway set $PORT
CMD ["sh", "-c", "uvicorn webapp.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
