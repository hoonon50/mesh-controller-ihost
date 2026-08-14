from __future__ import annotations

import os
import re
import threading
import time
from typing import Dict, Iterable, Tuple

from mesh_core import controller

VERSION = "6.3.2"
MAIN_ROUTER_IP = os.environ.get("MESH_MAIN_ROUTER_IP", "192.168.30.1")
SWEEP_SECONDS = max(15, int(os.environ.get("MESH_IP_RESOLVE_SWEEP_SECONDS", "60")))
CACHE_SECONDS = max(60, int(os.environ.get("MESH_IP_RESOLVE_CACHE_SECONDS", "300")))
SWEEP_BATCH = min(64, max(8, int(os.environ.get("MESH_IP_RESOLVE_SWEEP_BATCH", "48"))))
ACTIVE_SWEEP = os.environ.get("MESH_IP_RESOLVE_ACTIVE", "1").strip().lower() not in {"0", "false", "no", "off"}

MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$", re.I)

_cache_lock = threading.RLock()
_sweep_lock = threading.Lock()
_cache: Dict[str, Tuple[str, float]] = {}
_last_sweep = 0.0


def _normalize_macs(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        mac = str(value or "").strip().lower()
        if MAC_RE.fullmatch(mac):
            result.add(mac)
    return result


def _parse_tables(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}

    # Aktuální neighbour/ARP záznam má prioritu. Je čerstvější než případná
    # starší DHCP lease stejné MAC, například po přechodu zařízení na statickou IP.
    neigh_match = re.search(r"__NEIGH_BEGIN__\n(.*?)\n__NEIGH_END__", text, re.S)
    if neigh_match:
        for raw in neigh_match.group(1).splitlines():
            m = re.match(
                r"^(\S+)\s+dev\s+\S+.*?\slladdr\s+([0-9a-f:]{17})\b",
                raw.strip(),
                re.I,
            )
            if not m:
                continue
            ip, mac = m.group(1), m.group(2).lower()
            if MAC_RE.fullmatch(mac) and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
                result[mac] = ip

    lease_match = re.search(r"__LEASES_BEGIN__\n(.*?)\n__LEASES_END__", text, re.S)
    if lease_match:
        for raw in lease_match.group(1).splitlines():
            parts = raw.strip().split()
            if len(parts) < 3:
                continue
            mac = parts[1].lower()
            ip = parts[2]
            if MAC_RE.fullmatch(mac) and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
                # DHCP doplní MAC, kterou aktuální neighbour tabulka nezná.
                result.setdefault(mac, ip)

    return result


def _run_main(command: str, timeout: int) -> str:
    client = None
    try:
        client = controller.ssh_client(MAIN_ROUTER_IP, timeout=5)
        out, err, code = controller.command(client, command, timeout=timeout)
        if code != 0:
            raise RuntimeError((err or out).strip() or f"SSH rc={code}")
        return out
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def _read_main_tables() -> Dict[str, str]:
    command = r'''printf '__NEIGH_BEGIN__\n'
ip -4 neigh show dev br-lan 2>/dev/null || ip -4 neigh show 2>/dev/null || true
printf '__NEIGH_END__\n'
printf '__LEASES_BEGIN__\n'
cat /tmp/dhcp.leases 2>/dev/null || true
printf '__LEASES_END__\n'
'''
    try:
        return _parse_tables(_run_main(command, timeout=10))
    except Exception:
        return {}


def _active_sweep_main() -> Dict[str, str]:
    # Ping sweep zde neslouží k měření dostupnosti. Jeho účelem je vyvolat ARP
    # resolution na hlavním routeru. I klient, který ICMP Echo zahazuje, obvykle
    # musí odpovědět na ARP, aby mohl IPv4 na stejné LAN používat.
    command = f'''BATCH={SWEEP_BATCH}
CIDR="$(ip -4 -o addr show dev br-lan scope global 2>/dev/null | awk 'NR==1 {{print $4}}')"
ADDR="${{CIDR%/*}}"
PREFIX="${{CIDR#*/}}"
if command -v ping >/dev/null 2>&1 && [ "$PREFIX" = "24" ]; then
  BASE="$(echo "$ADDR" | awk -F. '{{print $1"."$2"."$3}}')"
  I=1
  while [ "$I" -le 254 ]; do
    N=0
    while [ "$N" -lt "$BATCH" ] && [ "$I" -le 254 ]; do
      ping -c 1 -W 1 "$BASE.$I" >/dev/null 2>&1 &
      I=$((I + 1))
      N=$((N + 1))
    done
    wait
  done
fi
printf '__NEIGH_BEGIN__\n'
ip -4 neigh show dev br-lan 2>/dev/null || ip -4 neigh show 2>/dev/null || true
printf '__NEIGH_END__\n'
printf '__LEASES_BEGIN__\n'
cat /tmp/dhcp.leases 2>/dev/null || true
printf '__LEASES_END__\n'
'''
    try:
        return _parse_tables(_run_main(command, timeout=25))
    except Exception:
        return {}


def _cache_update(values: Dict[str, str]) -> None:
    if not values:
        return
    now = time.monotonic()
    with _cache_lock:
        for mac, ip in values.items():
            if MAC_RE.fullmatch(mac) and ip:
                _cache[mac] = (ip, now)


def _cache_lookup(macs: set[str]) -> Dict[str, str]:
    now = time.monotonic()
    result: Dict[str, str] = {}
    with _cache_lock:
        for mac in list(_cache):
            ip, seen = _cache[mac]
            if now - seen > CACHE_SECONDS:
                _cache.pop(mac, None)
                continue
            if mac in macs:
                result[mac] = ip
    return result


def resolve_client_ipv4(macs: Iterable[str], *, allow_active_sweep: bool = True) -> Dict[str, str]:
    """Resolve known client MAC addresses to IPv4 without writing to /data.

    Resolution order:
      1) current main-router ARP/neighbour table, then DHCP leases,
      2) rate-limited active /24 ARP refresh via ping sweep,
      3) short-lived RAM cache from previous successful resolution.
    """
    wanted = _normalize_macs(macs)
    if not wanted:
        return {}

    current = _read_main_tables()
    _cache_update(current)
    result = {mac: current[mac] for mac in wanted if mac in current}
    unresolved = wanted.difference(result)

    if unresolved and ACTIVE_SWEEP and allow_active_sweep:
        global _last_sweep
        should_sweep = False
        now = time.monotonic()
        with _cache_lock:
            if now - _last_sweep >= SWEEP_SECONDS:
                should_sweep = True

        if should_sweep:
            with _sweep_lock:
                now = time.monotonic()
                with _cache_lock:
                    should_sweep = now - _last_sweep >= SWEEP_SECONDS
                    if should_sweep:
                        # Nastavíme čas před sweepem, aby paralelní requesty
                        # neodpálily další celý scan při pomalém/rozbitém SSH.
                        _last_sweep = now
                if should_sweep:
                    refreshed = _active_sweep_main()
                    _cache_update(refreshed)
                    for mac in unresolved:
                        if mac in refreshed:
                            result[mac] = refreshed[mac]
                    unresolved = wanted.difference(result)

    if unresolved:
        cached = _cache_lookup(unresolved)
        result.update(cached)

    return result
