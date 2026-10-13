FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p /app/data

EXPOSE 8000
# Development default: migrations run at startup (AUTO_MIGRATE=true).
# Production (APP_ENV=production) requires AUTO_MIGRATE=false: run `python scripts/migrate.py` first.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
