FROM python:3.12.3-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY api/ ./api/

ENV PYTHONPATH="/app" \
    PORT=8081

RUN useradd -m appuser
USER appuser

CMD ["bash","-lc","exec gunicorn api.src.server:app \
  --bind :${PORT:-8081} \
  --worker-class gthread \
  --workers 2 \
  --threads 8 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -"]




