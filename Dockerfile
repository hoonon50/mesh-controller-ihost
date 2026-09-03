FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8088 \
    TZ=Europe/Prague \
    WAN_USAGE_TIMEZONE=Europe/Prague \
    WAN_USAGE_POLL_SECONDS=30 \
    WAN_USAGE_SAVE_SECONDS=3600 \
    MESH_LIVE_TOPOLOGY_POLL=15 \
    MESH_LIVE_HEALTH_POLL=30 \
    MESH_NODE_FAILURE_GRACE=2 \
    MESH_LAN_CLIENT_TTL=45 \
    MESH_WIFI_POLICY_START_DELAY=20 \
    MESH_WIFI_POLICY_RETRY_SECONDS=30 \
    MESH_WIFI_POLICY_MAX_RETRIES=20 \
    MESH_WIFI_MAX_INACTIVITY=60 \
    MESH_WIFI_SKIP_INACTIVITY_POLL=0 \
    MESH_LAN_PORT_WATCH_SECONDS=15 \
    MESH_LAN_PROTECT_SCAN_SECONDS=60 \
    MESH_LAN_REASSERT_SECONDS=300 \
    MESH_LAN_ACTION_RETRY_SECONDS=60 \
    MESH_IP_RESOLVE_ACTIVE=1 \
    MESH_IP_RESOLVE_SWEEP_SECONDS=60 \
    MESH_IP_RESOLVE_CACHE_SECONDS=300 \
    MESH_IP_RESOLVE_SWEEP_BATCH=48

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-flask python3-paramiko gunicorn tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN mkdir -p /data/backups \
    && python3 -m py_compile /app/app.py /app/mesh_core.py /app/mesh_operation_manager.py /app/owut_manager.py /app/wan_usage.py /app/controller_backup_v701.py /app/live_topology_v503.py /app/wifi_ap_policy_v600.py /app/lan_port_control_v620.py /app/lan_port_inspector_v630.py /app/topology_inspector_v631.py /app/client_ip_resolver_v632.py /app/ihost_temperature_v636.py /app/v369_extra.py \
    && python3 -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('/app/templates')).get_template('index.html')"
EXPOSE 8088
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "10", "--timeout", "2600", "app:app"]
