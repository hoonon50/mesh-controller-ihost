FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8088

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-flask \
       python3-paramiko \
       gunicorn \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN mkdir -p /data/backups

EXPOSE 8088

CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "8", "--timeout", "1900", "app:app"]
