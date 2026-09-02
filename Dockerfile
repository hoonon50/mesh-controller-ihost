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
    && python3 /app/v600_wifi_ap_policy_patch.py \
    && python3 /app/v620_lan_port_control_patch.py \
    && python3 /app/v630_lan_port_inspector_patch.py \
    && python3 /app/v631_topology_inspector_patch.py \
    && python3 /app/v632_client_ip_resolver_patch.py \
    && python3 /app/v633_live_lan_ports_patch.py \
    && python3 /app/v634_owut_launcher_patch.py \
    && python3 /app/v635_extroot_recovery_patch.py \
    && python3 /app/v636_safe_preflight_ihost_temp_patch.py \
    && python3 /app/v636_persistent_owut_patch.py \
    && python3 /app/v637_reboot_order_report_patch.py \
    && python3 /app/v638_extroot_double_reboot_patch.py \
    && python3 /app/v639_single_owut_owner_patch.py \
    && python3 /app/v700_ssh_load_patch.py \
    && python3 /app/v701_controller_backup_patch.py \
    && python3 /app/v701_report_fix_patch.py \
    && python3 -m py_compile /app/app.py /app/mesh_operation_manager.py /app/controller_backup_v701.py /app/live_topology_v503.py /app/wifi_ap_policy_v600.py /app/lan_port_control_v620.py /app/lan_port_inspector_v630.py /app/topology_inspector_v631.py /app/client_ip_resolver_v632.py /app/ihost_temperature_v636.py /app/v500_patch.py /app/v503_live_topology_patch.py /app/v600_wifi_ap_policy_patch.py /app/v620_lan_port_control_patch.py /app/v630_lan_port_inspector_patch.py /app/v631_topology_inspector_patch.py /app/v632_client_ip_resolver_patch.py /app/v633_live_lan_ports_patch.py /app/v634_owut_launcher_patch.py /app/v635_extroot_recovery_patch.py /app/v636_safe_preflight_ihost_temp_patch.py /app/v637_reboot_order_report_patch.py /app/v638_extroot_double_reboot_patch.py /app/v639_single_owut_owner_patch.py /app/v700_ssh_load_patch.py /app/v701_controller_backup_patch.py /app/v701_report_fix_patch.py \
    && if [ -f /app/owut_manager.py ]; then python3 -m py_compile /app/owut_manager.py; fi \
    && python3 -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('/app/templates')).get_template('index.html')"
EXPOSE 8088
# Jeden worker: operation scheduler i live-topology collector musí být pouze jednou.
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "10", "--timeout", "2600", "app:app"]
