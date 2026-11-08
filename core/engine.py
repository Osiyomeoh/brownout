"""Brownout engine: holds state, turns readings into decisions, and runs the effects.

Effects go through injected callables (pause/resume a cron job, list jobs, notify), so the
engine is tested without Hermes and replay mode runs with every effect disabled.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from .forecast import Runway, runway
from .policy import Config, Decision, State, step
from .power import PowerSample

# A message that cannot be delivered (gateway restarting, router down with the power) stays in an
# in-order outbox and is retried every tick. Past this age it is dropped: an hour-old "power lost"
# would mislead more than it helps.
OUTBOX_MAX_AGE_S = 3600
LATE_AFTER_S = 60


@dataclass
class Effects:
    list_jobs: Callable[[], list[dict]] = lambda: []
    pause_job: Callable[[str, str], bool] = lambda job_id, reason: False
    resume_job: Callable[[str], bool] = lambda job_id: False
    notify: Callable[[str], bool] = lambda text: False
    log: Callable[[dict], None] = lambda event: None


@dataclass
class Engine:
    cfg: Config = field(default_factory=Config)
    fx: Effects = field(default_factory=Effects)
    state: State = State.ON_AC
    samples: deque = field(default_factory=lambda: deque(maxlen=720))
    paused_by_us: list[str] = field(default_factory=list)
    kept: bool = False
    runway_announced: bool = False
    battery_since: Optional[float] = None
    outbox: list = field(default_factory=list)      # undelivered messages, oldest first
    _human: Optional[str] = None
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ---- inputs -------------------------------------------------------------------------
    def command(self, cmd: str) -> None:
        """Queue a human command ("park", "keep", "resume"); applied on the next tick."""
        with self._lock:
            if cmd == "keep":
                self.kept = True
            else:
                self._human = cmd

    def tick(self, sample: Optional[PowerSample]) -> Decision:
        with self._lock:
            if sample is not None:
                self.samples.append(sample)
            if self.outbox:
                self._flush(sample.t if sample else time.time())
            rw = runway(list(self.samples), floor_pct=5.0)
            human, self._human = self._human, None
            prev = self.state
            d = step(prev, sample, rw, self.cfg, human=human, kept=self.kept)
            self.state = d.state
            self._outage_s = (sample.t - self.battery_since) if (
                sample is not None and self.battery_since is not None) else None
            if sample is not None and sample.on_ac:
                self.kept, self.runway_announced, self.battery_since = False, False, None
            elif sample is not None and self.battery_since is None:
                self.battery_since = sample.t
            for a in d.actions:
                getattr(self, f"_do_{a}")(sample, rw)
            if (self.state == State.ON_BATTERY and not self.runway_announced and rw.minutes is not None):
                self.runway_announced = True
                self._send(f"Brownout: measured runway about {rw.minutes:.0f} min ({rw.basis}). "
                           f"{self._jobs_line()} Reply /brownout park or /brownout keep.", "runway", sample)
            self.fx.log({"t": sample.t if sample else time.time(), "event": "tick", "prev": prev.value,
                         "state": d.state.value, "actions": d.actions, "reason": d.reason,
                         "pct": sample.pct if sample else None, "on_ac": sample.on_ac if sample else None,
                         "runway_min": rw.minutes})
            return d

    # ---- effects ------------------------------------------------------------------------
    def _active_jobs(self) -> list[dict]:
        try:
            return [j for j in self.fx.list_jobs() if j.get("enabled", True) and j.get("state") != "paused"]
        except Exception:
            return []

    def _jobs_line(self) -> str:
        jobs = self._active_jobs()
        if not jobs:
            return "No scheduled jobs are active."
        names = ", ".join(j.get("name") or j.get("id", "?") for j in jobs[:5])
        return f"{len(jobs)} scheduled job(s) active: {names}."

    def _send(self, text: str, kind: str, sample: Optional[PowerSample]) -> None:
        now = sample.t if sample else time.time()
        self.outbox.append({"text": text, "kind": kind, "t": now})
        self._flush(now)

    def _flush(self, now: float) -> None:
        """Deliver queued messages in order; stop at the first failure and retry next tick."""
        while self.outbox:
            m = self.outbox[0]
            age = now - m["t"]
            if age > OUTBOX_MAX_AGE_S:
                self.outbox.pop(0)
                self.fx.log({"t": time.time(), "event": "notify_dropped", "kind": m["kind"],
                             "age_s": round(age), "text": m["text"]})
                continue
            text = m["text"] if age < LATE_AFTER_S else f"[delayed {int(age // 60)} min] {m['text']}"
            try:
                ok = bool(self.fx.notify(text))
            except Exception:
                ok = False
            self.fx.log({"t": time.time(), "event": "notify", "kind": m["kind"], "delivered": ok,
                         "text": text, "sample_t": m["t"]})
            if not ok:
                return
            self.outbox.pop(0)

    def _do_alert(self, s: Optional[PowerSample], rw: Runway) -> None:
        pct = f"{s.pct:.0f}%" if s and s.pct is not None else "unknown charge"
        os_est = ""
        if s and s.os_minutes_left:
            h, m = divmod(int(s.os_minutes_left), 60)
            os_est = f" The OS estimates {h}:{m:02d} left."
        self._send(f"Brownout: power lost on this machine. Battery {pct}.{os_est} Measuring the real drain now. "
                   f"{self._jobs_line()} Reply /brownout park to pause them and stop new tool calls, "
                   f"or /brownout keep to carry on.", "alert", s)

    def _do_park(self, s: Optional[PowerSample], rw: Runway) -> None:
        paused = []
        for j in self._active_jobs():
            try:
                if self.fx.pause_job(j["id"], "brownout: host on battery"):
                    paused.append(j["id"])
            except Exception:
                pass
        self.paused_by_us.extend(paused)
        self._send(f"Brownout: parked. Paused {len(paused)} scheduled job(s); new tool calls are held. "
                   f"Nothing was stopped mid-write, killed or deleted. Reply /brownout resume to undo.",
                   "park", s)

    def _do_resume(self, s: Optional[PowerSample], rw: Runway) -> None:
        resumed = []
        for job_id in self.paused_by_us:
            try:
                if self.fx.resume_job(job_id):
                    resumed.append(job_id)
            except Exception:
                pass
        self.paused_by_us = [j for j in self.paused_by_us if j not in resumed]
        self._resumed = resumed

    def _do_notify_resumed(self, s: Optional[PowerSample], rw: Runway) -> None:
        n = len(getattr(self, "_resumed", []))
        self._send(f"Brownout: power is back. Resumed {n} job(s) Brownout had paused; tool calls are open again.",
                   "resumed", s)

    def _do_notify_back(self, s: Optional[PowerSample], rw: Runway) -> None:
        dur = getattr(self, "_outage_s", None)
        took = f" after {dur / 60:.0f} min on battery" if dur and dur >= 60 else ""
        self._send(f"Brownout: power is back{took}. Nothing was parked.", "back", s)

    def _do_notify_unknown(self, s: Optional[PowerSample], rw: Runway) -> None:
        self._send("Brownout: no power reading is available, so Brownout is taking no action.", "unknown", s)

    # ---- queries ------------------------------------------------------------------------
    @property
    def parked(self) -> bool:
        return self.state == State.PARKED

    def status(self) -> str:
        with self._lock:
            last = self.samples[-1] if self.samples else None
            rw = runway(list(self.samples))
            src = "no reading yet" if last is None else (
                f"{'mains' if last.on_ac else 'battery'}, {last.pct:.0f}% via {last.source}"
                if last.pct is not None else f"{'mains' if last.on_ac else 'battery'} via {last.source}")
            run = f"{rw.minutes:.0f} min ({rw.basis})" if rw.minutes is not None else rw.basis
            return json.dumps({"state": self.state.value, "power": src, "runway": run,
                               "paused_by_brownout": self.paused_by_us, "keep": self.kept,
                               "undelivered": len(self.outbox)})
