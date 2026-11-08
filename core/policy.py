"""Decide what Brownout does on each power reading. Pure: returns actions, performs none.

States: ON_AC -> ON_BATTERY (alert sent, waiting for the human) -> PARKED -> ON_AC (resume).
The only automatic action without a human answer is a reversible park at the critical level.
Brownout never kills processes, deletes files or edits jobs beyond pause/resume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .forecast import Runway
from .power import PowerSample


class State(str, Enum):
    ON_AC = "on_ac"
    ON_BATTERY = "on_battery"
    PARKED = "parked"
    UNKNOWN = "unknown"


@dataclass
class Config:
    critical_pct: float = 15.0        # auto-park (reversible) at or below this, if no answer
    critical_minutes: float = 10.0    # ...or when measured runway drops below this
    auto_resume: bool = True          # resume what Brownout paused when power returns


@dataclass
class Decision:
    state: State
    actions: list[str] = field(default_factory=list)   # "alert", "park", "resume", "notify_resumed", "notify_back", "notify_unknown"
    reason: str = ""


def step(prev: State, sample: Optional[PowerSample], rw: Runway, cfg: Config,
         human: Optional[str] = None, kept: bool = False) -> Decision:
    """One tick. `human` is a fresh command from the user: "park", "keep" or "resume".
    `kept` is True when the user already said "keep" during this battery stretch."""
    if sample is None:
        if prev == State.UNKNOWN:
            return Decision(State.UNKNOWN, [], "still no power reading")
        return Decision(State.UNKNOWN, ["notify_unknown"],
                        "no power reading available; Brownout will not guess and takes no action")

    if sample.on_ac:
        if prev == State.PARKED and (cfg.auto_resume or human == "resume"):
            return Decision(State.ON_AC, ["resume", "notify_resumed"], "power is back")
        if prev == State.PARKED:
            return Decision(State.PARKED, [], "power is back; waiting for /brownout resume")
        if prev == State.ON_BATTERY:
            return Decision(State.ON_AC, ["notify_back"], "power is back")
        return Decision(State.ON_AC, [], "on mains power")

    # On battery from here on.
    if human == "park" and prev != State.PARKED:
        return Decision(State.PARKED, ["park"], "you chose to park")
    if human == "resume" and prev == State.PARKED:
        return Decision(State.ON_BATTERY, ["resume"], "you chose to resume on battery")
    if prev in (State.ON_AC, State.UNKNOWN):
        return Decision(State.ON_BATTERY, ["alert"], "power lost")
    if prev == State.PARKED:
        return Decision(State.PARKED, [], "parked on battery")

    critical = (sample.pct is not None and sample.pct <= cfg.critical_pct) or \
               (rw.minutes is not None and rw.minutes <= cfg.critical_minutes)
    if critical and not kept:
        return Decision(State.PARKED, ["park"],
                        "critical battery and no answer: reversible park (nothing killed or deleted)")
    return Decision(State.ON_BATTERY, [], "on battery")
