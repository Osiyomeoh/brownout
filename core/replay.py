"""Replay a recorded power trace through the real engine with every side effect disabled."""
from __future__ import annotations

import json
from pathlib import Path

from .engine import Effects, Engine
from .policy import Config
from .power import parse_pmset


def load_trace(path: Path):
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        yield parse_pmset(rec["pmset"], t=rec["t"])


def replay(path: Path, cfg: Config | None = None, commands: dict[int, str] | None = None) -> list[str]:
    """Run the trace; `commands` maps sample index -> human command. Returns a transcript."""
    out: list[str] = []
    sent: list[str] = []
    fx = Effects(notify=lambda text: sent.append(f"  [would send] {text}") or True,
                 list_jobs=lambda: [{"id": "replay-job", "name": "nightly-report", "enabled": True}],
                 pause_job=lambda job_id, reason: True, resume_job=lambda job_id: True)
    eng = Engine(cfg=cfg or Config(), fx=fx)
    t0 = None
    for i, sample in enumerate(load_trace(path)):
        if commands and i in commands:
            eng.command(commands[i])
            out.append(f"  [you] /brownout {commands[i]}")
        d = eng.tick(sample)
        t0 = t0 if t0 is not None else (sample.t if sample else 0)
        if d.actions or sent or i == 0:
            mins = ((sample.t - t0) / 60) if sample else 0
            pw = "no reading" if sample is None else (
                f"{'AC' if sample.on_ac else 'battery'} {sample.pct:.0f}%" if sample.pct is not None
                else ("AC" if sample.on_ac else "battery"))
            out.append(f"+{mins:5.1f} min  {pw:<12} -> {d.state.value} {d.actions} ({d.reason})")
        out.extend(sent)
        sent.clear()
    return out
