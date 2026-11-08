"""Read the host's power state. Every reader returns a PowerSample or None (never a guess)."""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PowerSample:
    t: float                  # unix seconds
    on_ac: bool
    pct: Optional[float]      # battery charge 0-100, None when the source has no battery reading
    source: str               # "pmset" | "sysfs" | "nut"
    os_minutes_left: Optional[float] = None  # the OS's own estimate, kept for comparison only


_PMSET_PCT = re.compile(r"(\d+)%;\s*([^;]+);\s*(?:(\d+):(\d+)|\(no estimate\))?")


def parse_pmset(raw: str, t: Optional[float] = None) -> Optional[PowerSample]:
    """Parse `pmset -g batt` output. Returns None if no battery line is present."""
    m = _PMSET_PCT.search(raw)
    if not m:
        return None
    on_ac = "'AC Power'" in raw
    mins = None
    if m.group(3) is not None:
        mins = int(m.group(3)) * 60 + int(m.group(4))
    return PowerSample(t=t if t is not None else time.time(), on_ac=on_ac, pct=float(m.group(1)),
                       source="pmset", os_minutes_left=mins)


def parse_sysfs(root: Path, t: Optional[float] = None) -> Optional[PowerSample]:
    """Read Linux /sys/class/power_supply. Mains online => on_ac. None when no battery exists."""
    if not root.is_dir():
        return None
    on_ac, pct, saw_battery = False, None, False
    for dev in sorted(root.iterdir()):
        kind = _read(dev / "type")
        if kind == "Mains" and _read(dev / "online") == "1":
            on_ac = True
        elif kind == "Battery":
            saw_battery = True
            cap = _read(dev / "capacity")
            if cap and cap.isdigit():
                pct = float(cap)
            if _read(dev / "status") in ("Charging", "Full"):
                on_ac = True
    if not saw_battery:
        return None
    return PowerSample(t=t if t is not None else time.time(), on_ac=on_ac, pct=pct, source="sysfs")


def parse_upsc(raw: str, t: Optional[float] = None) -> Optional[PowerSample]:
    """Parse NUT `upsc <ups>` output. ups.status contains OL (on line) or OB (on battery)."""
    vals = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
    status = vals.get("ups.status", "").split()
    if not status:
        return None
    charge = vals.get("battery.charge")
    runtime = vals.get("battery.runtime")
    return PowerSample(t=t if t is not None else time.time(), on_ac="OL" in status and "OB" not in status,
                       pct=float(charge) if charge else None, source="nut",
                       os_minutes_left=float(runtime) / 60 if runtime else None)


def _read(p: Path) -> Optional[str]:
    try:
        return p.read_text().strip()
    except OSError:
        return None


def read_now(ups: Optional[str] = None) -> Optional[PowerSample]:
    """Best available live reading: NUT (if configured), then macOS pmset, then Linux sysfs."""
    if ups:
        out = _run(["upsc", ups])
        if out and (s := parse_upsc(out)):
            return s
    out = _run(["pmset", "-g", "batt"])
    if out and (s := parse_pmset(out)):
        return s
    return parse_sysfs(Path("/sys/class/power_supply"))


def _run(cmd: list[str]) -> Optional[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
