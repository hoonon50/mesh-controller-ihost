FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8088 \
    TZ=Europe/Prague \
    WAN_USAGE_TIMEZONE=Europe/Prague \
    WAN_USAGE_POLL_SECONDS=30 \
    WAN_USAGE_SAVE_SECONDS=3600

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-flask \
       python3-paramiko \
       gunicorn \
       tzdata \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN mkdir -p /data/backups \
    && python3 /app/v369_patch.py \
    && python3 /app/owut_patch.py \
    && python3 /app/refresh_patch.py \
    && if [ -f /app/v388_reorder_patch.py ]; then python3 /app/v388_reorder_patch.py; fi \
    && python3 /app/v389_wan_usage_patch.py \
    && python3 /app/v3812_wan_history_patch.py \
    && python3 -m py_compile /app/app.py /app/owut_manager.py /app/wan_usage.py /app/v3812_wan_history_patch.py \
    && python3 -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('/app/templates')).get_template('index.html')"
EXPOSE 8088
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "8", "--timeout", "1900", "app:app"]
