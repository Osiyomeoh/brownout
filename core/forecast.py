"""Forecast battery runway from measured discharge since the plug was pulled."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .power import PowerSample

MIN_SPAN_S = 120      # need at least 2 minutes of discharge before we trust a slope
MIN_POINTS = 3
MIN_TICKS = 3         # three downward ticks = two full percent-steps of measured drain


@dataclass(frozen=True)
class Runway:
    minutes: Optional[float]    # None = unknown (not enough data); never a guess
    pct_per_min: Optional[float]
    basis: str                  # human-readable explanation of how it was computed


def runway(samples: Sequence[PowerSample], floor_pct: float = 5.0) -> Runway:
    """Least-squares slope of charge vs time over the current battery stretch.

    Only samples after the most recent switch to battery are used. Returns minutes until
    `floor_pct` is reached, or minutes=None when there is not enough evidence yet.
    """
    stretch: list[PowerSample] = []
    for s in samples:
        if s.on_ac:
            stretch = []
        elif s.pct is not None:
            stretch.append(s)
    if len(stretch) < MIN_POINTS or stretch[-1].t - stretch[0].t < MIN_SPAN_S:
        return Runway(None, None, f"measuring ({len(stretch)} readings on battery so far)")
    # OS charge readings are whole percents, so a flat run says nothing about the rate (a least-
    # squares fit over plateaus reads near zero and forecasts days). Each downward tick marks the
    # moment the true charge crossed a whole percent, so the rate is measured tick-to-tick.
    ticks = [(b.t, b.pct) for a, b in zip(stretch, stretch[1:]) if b.pct < a.pct]
    if len(ticks) < MIN_TICKS:
        return Runway(None, None, f"charge not falling yet ({len(ticks)} of {MIN_TICKS} drops seen)")
    (t1, p1), (t2, p2) = ticks[0], ticks[-1]
    if t2 <= t1:
        return Runway(None, None, "charge not falling yet")
    rate = (p1 - p2) / ((t2 - t1) / 60)
    left = max(0.0, (stretch[-1].pct - floor_pct) / rate)
    return Runway(left, rate, f"{rate:.2f}%/min, {p1 - p2:.0f} pts over {(t2 - t1) / 60:.0f} min")
