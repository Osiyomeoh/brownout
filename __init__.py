"""Brownout: notices when the Hermes host loses mains power, measures battery runway,
tells you, and parks agent work until power is back.

Wiring only; logic lives in core/ and is tested without Hermes.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .core.engine import Effects, Engine
from .core.policy import Config
from .core.power import read_now

log = logging.getLogger("brownout")

_ENGINE: Engine | None = None
_UPS: str | None = None
_OWN = threading.local()          # set while Brownout itself dispatches a tool
_LOCK_FH = None                   # held for process lifetime: one watcher per HERMES_HOME
_ALLOW_WHEN_PARKED = {"cronjob_manage"}
_ENGINE_LOCK = threading.RLock()   # watcher thread and command handler share one engine


def _data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir("brownout")


def _setting(ctx, key, default):
    try:
        v = ctx.get_config(key)
    except Exception:
        v = None
    return default if v is None else v


def _dispatch(ctx, tool: str, args: dict) -> dict:
    _OWN.active = True
    try:
        raw = ctx.dispatch_tool(tool, args)
    finally:
        _OWN.active = False
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        return {"raw": raw}


def _effects(ctx, events: Path) -> Effects:
    target = str(_setting(ctx, "notify_target", "telegram"))

    def list_jobs():
        res = _dispatch(ctx, "cronjob_manage", {"action": "list"})
        return [{"id": j.get("job_id"), "name": j.get("name"), "enabled": j.get("enabled", True),
                 "state": j.get("state")} for j in res.get("jobs", [])]

    def pause_job(job_id, reason):
        return bool(_dispatch(ctx, "cronjob_manage",
                              {"action": "pause", "job_id": job_id, "reason": reason}).get("success"))

    def resume_job(job_id):
        return bool(_dispatch(ctx, "cronjob_manage", {"action": "resume", "job_id": job_id}).get("success"))

    def notify(text):
        # send_message is deliberately not an agent-callable tool, so the public route is the
        # documented `hermes send` CLI: gateway credentials + home channel, no agent turn.
        # Exit codes: 0 ok, 1 delivery error, 2 usage error.
        cmd = ([shutil.which("hermes")] if shutil.which("hermes")
               else [sys.executable, "-m", "hermes_cli.main"])
        try:
            p = subprocess.run(cmd + ["send", "--to", target, "--file", "-"], input=text,
                               capture_output=True, text=True, timeout=30)
            ok, res = p.returncode == 0, {"exit": p.returncode, "out": (p.stderr + p.stdout).strip()[-300:]}
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, res = False, {"error": f"{type(e).__name__}: {e}"}
        if not ok:
            log.warning("brownout: send to %s failed: %s", target, res)
        return ok

    def write_event(ev):
        try:
            with events.open("a") as fh:
                fh.write(json.dumps(ev) + "\n")
        except OSError:
            pass

    return Effects(list_jobs=list_jobs, pause_job=pause_job, resume_job=resume_job,
                   notify=notify, log=write_event)


# ---- shared state ---------------------------------------------------------------------------
# One process (the lock holder) owns the engine. Every other Hermes process on the same home
# reads state.json for the guard and status, and hands park/keep/resume to the owner through
# commands.jsonl, so two processes never pause or resume jobs independently.
_IS_OWNER = False
_STATE_CACHE = {"mtime": None, "data": {}}


def _write_state(engine: Engine) -> None:
    p = _data_dir() / "state.json"
    tmp = p.with_name(f"state.{os.getpid()}.{threading.get_ident()}.tmp")   # one per writer
    tmp.write_text(engine.status())
    tmp.replace(p)


def _read_state() -> dict:
    p = _data_dir() / "state.json"
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    if m != _STATE_CACHE["mtime"]:
        try:
            _STATE_CACHE.update(mtime=m, data=json.loads(p.read_text()))
        except (OSError, ValueError):
            return _STATE_CACHE["data"]
    return _STATE_CACHE["data"]


def _drain_commands(engine: Engine) -> None:
    p = _data_dir() / "commands.jsonl"
    try:
        taken = p.with_suffix(".taking")
        p.replace(taken)
    except OSError:
        return
    for line in taken.read_text().splitlines():
        try:
            cmd = json.loads(line).get("cmd")
        except ValueError:
            continue
        if cmd in ("park", "keep", "resume"):
            engine.command(cmd)
    taken.unlink(missing_ok=True)


def _watch(engine: Engine, interval: float, ups: str | None) -> None:
    while True:
        try:
            sample = read_now(ups=ups)
            with _ENGINE_LOCK:
                _drain_commands(engine)
                engine.tick(sample)
                _write_state(engine)
        except Exception:
            log.exception("brownout: tick failed")
        time.sleep(interval)


def _start_watcher(ctx, engine: Engine) -> bool:
    global _LOCK_FH, _IS_OWNER
    fh = (_data_dir() / "watcher.lock").open("w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False          # another Hermes process on this home already watches
    _LOCK_FH, _IS_OWNER = fh, True
    interval = float(_setting(ctx, "poll_seconds", 15))
    threading.Thread(target=_watch, args=(engine, interval, _UPS), name="brownout-watcher",
                     daemon=True).start()
    return True


def _guard(*, tool_name, args=None, **kw):
    if _ENGINE is None or getattr(_OWN, "active", False):
        return None
    parked = _ENGINE.parked if _IS_OWNER else _read_state().get("state") == "parked"
    if not parked:
        return None
    if tool_name in _ALLOW_WHEN_PARKED:
        return None
    return {"action": "block",
            "message": "Brownout: this machine is on battery and work is parked. "
                       "The call was not run. Reply /brownout resume to continue anyway."}


HELP = ("/brownout status | park | keep | resume | test-alert | replay <trace.jsonl>")


def _command(raw_args: str) -> str:
    parts = (raw_args or "").split()
    sub = parts[0] if parts else "status"
    eng = _ENGINE
    if eng is None:
        return "Brownout is not running."
    if sub == "status":
        return eng.status() if _IS_OWNER else (json.dumps(_read_state()) or "No watcher running.")
    if sub in ("park", "keep", "resume"):
        if not _IS_OWNER:
            with (_data_dir() / "commands.jsonl").open("a") as fh:
                fh.write(json.dumps({"cmd": sub, "t": time.time()}) + "\n")
            return f"Brownout: {sub} sent to the watcher; it applies within one poll."
        sample = read_now(ups=_UPS) if sub != "keep" else None
        with _ENGINE_LOCK:
            eng.command(sub)
            if sample is not None:
                eng.tick(sample)
            _write_state(eng)
            if sub == "park" and not eng.parked:
                return "Brownout: this machine is on mains power, so there is nothing to park. " + eng.status()
            return f"Brownout: {sub} applied. " + eng.status()
    if sub == "test-alert":
        ok = eng.fx.notify("Brownout test: alerts from this machine reach you here.")
        return "Test alert sent." if ok else "Test alert failed; check notify_target and the gateway."
    if sub == "replay":
        if len(parts) < 2:
            return "Usage: /brownout replay <trace.jsonl>"
        from .core.replay import replay
        try:
            return "\n".join(replay(Path(parts[1]).expanduser()))
        except (OSError, ValueError, KeyError) as e:
            return f"Replay failed: {e}"
    return HELP


def register(ctx):
    global _ENGINE, _UPS
    _UPS = _setting(ctx, "ups", None)
    cfg = Config(critical_pct=float(_setting(ctx, "critical_pct", 15)),
                 critical_minutes=float(_setting(ctx, "critical_minutes", 10)),
                 auto_resume=bool(_setting(ctx, "auto_resume", True)))
    _ENGINE = Engine(cfg=cfg, fx=_effects(ctx, _data_dir() / "events.jsonl"))
    ctx.register_hook("pre_tool_call", _guard)
    ctx.register_command("brownout", _command, description="Power-loss guard for this Hermes host",
                         args_hint="status|park|keep|resume|test-alert|replay <trace>")
    if _setting(ctx, "watch", True):
        _start_watcher(ctx, _ENGINE)
