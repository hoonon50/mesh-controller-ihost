from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Tuple

VERSION = "6.3.6"
def _normalize_temp(raw: str) -> Optional[float]:
    try:
        value = float(str(raw).strip())
    except Exception:
        return None
    if abs(value) >= 1000:
        value /= 1000.0
    if not (-20.0 <= value <= 150.0):
        return None
    return round(value, 1)


def _pick_temperature(candidates: List[Tuple[str, float]]) -> Optional[float]:
    if not candidates:
        return None

    def score(item: Tuple[str, float]) -> Tuple[int, float]:
        label, value = item
        low = label.lower()
        rank = 0
        for token, points in (
            ("cpu", 120),
            ("soc", 110),
            ("package", 100),
            ("core", 90),
            ("thermal", 70),
            ("board", 40),
        ):
            if token in low:
                rank = max(rank, points)
        return rank, value

    return max(candidates, key=score)[1]


def _read_once() -> Optional[float]:
    candidates: List[Tuple[str, float]] = []

    thermal = Path("/sys/class/thermal")
    if thermal.exists():
        for zone in thermal.glob("thermal_zone*"):
            try:
                temp_path = zone / "temp"
                if not temp_path.is_file():
                    continue
                type_path = zone / "type"
                label = (
                    type_path.read_text(encoding="utf-8", errors="ignore").strip()
                    if type_path.is_file()
                    else zone.name
                )
                value = _normalize_temp(temp_path.read_text(encoding="utf-8", errors="ignore"))
                if value is not None:
                    candidates.append((label, value))
            except Exception:
                pass

    hwmon = Path("/sys/class/hwmon")
    if hwmon.exists():
        for inp in hwmon.glob("hwmon*/temp*_input"):
            try:
                if not inp.is_file():
                    continue
                label_path = Path(str(inp)[:-6] + "_label")
                name_path = inp.parent / "name"
                if label_path.is_file():
                    label = label_path.read_text(encoding="utf-8", errors="ignore").strip()
                elif name_path.is_file():
                    label = name_path.read_text(encoding="utf-8", errors="ignore").strip()
                else:
                    label = inp.name
                value = _normalize_temp(inp.read_text(encoding="utf-8", errors="ignore"))
                if value is not None:
                    candidates.append((label, value))
            except Exception:
                pass

    return _pick_temperature(candidates)


def read_ihost_temperature(retries: int = 3, delay: float = 0.20) -> Optional[float]:
    """Vrátí CPU/SoC teplotu hostitele iHost z host sysfs viditelného v Dockeru.

    Používá pouze skutečné thermal_zone*/temp a hwmon temp*_input soubory,
    nikoli temp*_max/crit/label. Krátké opakování eliminuje přechodné sysfs čtení
    při okamžiku generování reportu.
    """
    attempts = max(1, int(retries))
    for index in range(attempts):
        value = _read_once()
        if value is not None:
            return value
        if index + 1 < attempts:
            time.sleep(max(0.0, float(delay)))
    return None
