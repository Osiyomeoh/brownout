"""Unit tests for power parsing, forecast and policy. pmset strings are real outputs captured from this Mac."""
from pathlib import Path
import pytest
from core.power import parse_pmset, parse_sysfs, parse_upsc, PowerSample
from core.forecast import runway
from core.policy import step, State, Config

REAL_BATT = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=22544483)\t72%; discharging; 3:22 remaining present: true\n"
REAL_AC = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=22544483)\t100%; finishing charge; 0:10 remaining present: true\n"
NO_BATT = "Now drawing from 'AC Power'\n"


def test_pmset_battery():
    s = parse_pmset(REAL_BATT, t=0)
    assert (s.on_ac, s.pct, s.os_minutes_left, s.source) == (False, 72.0, 202, "pmset")

def test_pmset_ac():
    s = parse_pmset(REAL_AC, t=0)
    assert s.on_ac and s.pct == 100.0

def test_pmset_no_battery_is_none_not_guess():
    assert parse_pmset(NO_BATT) is None

def test_pmset_no_estimate():
    s = parse_pmset("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t50%; discharging; (no estimate) present: true", t=0)
    assert s.pct == 50.0 and s.os_minutes_left is None

def _dev(root, name, **files):
    d = root / name; d.mkdir()
    for k, v in files.items(): (d / k).write_text(v)

def test_sysfs_on_battery(tmp_path):
    _dev(tmp_path, "AC", type="Mains", online="0")
    _dev(tmp_path, "BAT0", type="Battery", capacity="64", status="Discharging")
    s = parse_sysfs(tmp_path, t=0)
    assert not s.on_ac and s.pct == 64.0

def test_sysfs_on_mains(tmp_path):
    _dev(tmp_path, "AC", type="Mains", online="1")
    _dev(tmp_path, "BAT0", type="Battery", capacity="90", status="Charging")
    assert parse_sysfs(tmp_path, t=0).on_ac

def test_sysfs_no_battery_is_none(tmp_path):
    _dev(tmp_path, "AC", type="Mains", online="1")
    assert parse_sysfs(tmp_path) is None
    assert parse_sysfs(tmp_path / "missing") is None

def test_upsc_on_battery():
    s = parse_upsc("battery.charge: 80\nbattery.runtime: 1200\nups.status: OB DISCHRG\n", t=0)
    assert not s.on_ac and s.pct == 80.0 and s.os_minutes_left == 20

def test_upsc_online():
    assert parse_upsc("battery.charge: 100\nups.status: OL\n", t=0).on_ac

def test_upsc_empty_is_none():
    assert parse_upsc("Error: Driver not connected\n") is None

def S(t, pct, ac=False): return PowerSample(t=t, on_ac=ac, pct=pct, source="test")

def test_runway_unknown_until_enough_evidence():
    assert runway([S(0, 90), S(30, 89.9)]).minutes is None

def test_runway_linear():
    # 1% per minute from 80%: 75 minutes to the 5% floor
    r = runway([S(i * 60, 80 - i) for i in range(6)])
    assert r.pct_per_min == pytest.approx(1.0) and r.minutes == pytest.approx(70.0)

def test_runway_resets_on_ac():
    r = runway([S(0, 50), S(600, 40), S(700, 40, ac=True), S(800, 60), S(830, 60)])
    assert r.minutes is None

def test_runway_not_falling():
    assert runway([S(i * 60, 80) for i in range(4)]).minutes is None

C = Config()
UNK = runway([])

def test_power_loss_alerts():
    d = step(State.ON_AC, S(0, 90), UNK, C)
    assert d.state == State.ON_BATTERY and d.actions == ["alert"]

def test_human_park():
    d = step(State.ON_BATTERY, S(0, 90), UNK, C, human="park")
    assert d.state == State.PARKED and d.actions == ["park"]

def test_no_answer_critical_parks_reversibly():
    d = step(State.ON_BATTERY, S(0, 14), UNK, C)
    assert d.state == State.PARKED and d.actions == ["park"] and "reversible" in d.reason

def test_keep_overrides_critical():
    assert step(State.ON_BATTERY, S(0, 14), UNK, C, kept=True).actions == []

def test_critical_by_runway():
    rw = runway([S(i * 60, 30 - 3 * i) for i in range(6)])  # 3%/min, 15% left -> ~3 min
    assert step(State.ON_BATTERY, S(300, 15.5), rw, C).actions == ["park"]

def test_resume_on_power_return():
    d = step(State.PARKED, S(0, 20, ac=True), UNK, C)
    assert d.state == State.ON_AC and d.actions == ["resume", "notify_resumed"]

def test_power_back_without_park_says_so_once():
    d = step(State.ON_BATTERY, S(0, 20, ac=True), UNK, C)
    assert d.state == State.ON_AC and d.actions == ["notify_back"]
    assert step(State.ON_AC, S(30, 20, ac=True), UNK, C).actions == []

def test_no_auto_resume_waits_for_human():
    cfg = Config(auto_resume=False)
    assert step(State.PARKED, S(0, 20, ac=True), UNK, cfg).state == State.PARKED
    assert step(State.PARKED, S(0, 20, ac=True), UNK, cfg, human="resume").actions[0] == "resume"

def test_unknown_reading_takes_no_action():
    d = step(State.ON_BATTERY, None, UNK, C)
    assert d.state == State.UNKNOWN and "park" not in d.actions and d.actions == ["notify_unknown"]
    assert step(State.UNKNOWN, None, UNK, C).actions == []

def test_parked_stays_parked_on_battery():
    assert step(State.PARKED, S(0, 10), UNK, C).actions == []
