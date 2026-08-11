FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8088 \
    TZ=Europe/Prague \
    WAN_USAGE_TIMEZONE=Europe/Prague \
    WAN_USAGE_POLL_SECONDS=30 \
    WAN_USAGE_SAVE_SECONDS=3600 \
    MESH_LIVE_TOPOLOGY_POLL=5 \
    MESH_LIVE_HEALTH_POLL=15 \
    MESH_NODE_FAILURE_GRACE=2

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
    && if [ -f /app/v369_patch.py ]; then python3 /app/v369_patch.py; fi \
    && if [ -f /app/owut_patch.py ]; then python3 /app/owut_patch.py; fi \
    && if [ -f /app/refresh_patch.py ]; then python3 /app/refresh_patch.py; fi \
    && if [ -f /app/v388_reorder_patch.py ]; then python3 /app/v388_reorder_patch.py; fi \
    && if [ -f /app/v389_wan_usage_patch.py ]; then python3 /app/v389_wan_usage_patch.py; fi \
    && if [ -f /app/v3812_wan_history_patch.py ]; then python3 /app/v3812_wan_history_patch.py; fi \
    && python3 /app/v500_patch.py \
    && python3 /app/v503_live_topology_patch.py \
    && python3 -m py_compile /app/app.py /app/mesh_operation_manager.py /app/live_topology_v503.py /app/v500_patch.py /app/v503_live_topology_patch.py \
    && if [ -f /app/owut_manager.py ]; then python3 -m py_compile /app/owut_manager.py; fi \
    && python3 -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('/app/templates')).get_template('index.html')"
EXPOSE 8088
# Jeden worker: operation scheduler i live-topology collector musí být pouze jednou.
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "10", "--timeout", "2600", "app:app"]
