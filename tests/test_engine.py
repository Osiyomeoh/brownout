import json

from core.engine import Effects, Engine
from core.policy import Config, State
from core.power import parse_pmset
from core.replay import replay

BATT = ("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=22544483)\t{p}%; discharging; "
        "3:22 remaining present: true")
AC = ("Now drawing from 'AC Power'\n -InternalBattery-0 (id=22544483)\t{p}%; charging; "
      "0:10 remaining present: true")


def s(raw, p, t):
    return parse_pmset(raw.format(p=p), t=t)


class FakeHermes:
    def __init__(self):
        self.jobs = {"j1": {"id": "j1", "name": "nightly", "enabled": True, "state": "scheduled"},
                     "j2": {"id": "j2", "name": "off", "enabled": False, "state": "paused"}}
        self.sent, self.events = [], []

    def fx(self):
        def pause(i, r):
            self.jobs[i].update(enabled=False, state="paused")
            return True

        def resume(i):
            self.jobs[i].update(enabled=True, state="scheduled")
            return True
        return Effects(list_jobs=lambda: list(self.jobs.values()), pause_job=pause, resume_job=resume,
                       notify=lambda t: self.sent.append(t) or True, log=self.events.append)


def test_unplug_alerts_then_human_park_and_auto_resume():
    h = FakeHermes()
    e = Engine(fx=h.fx())
    e.tick(s(AC, 90, 0))
    assert not h.sent
    e.tick(s(BATT, 90, 30))
    assert e.state == State.ON_BATTERY and "power lost" in h.sent[0] and "nightly" in h.sent[0]
    e.command("park")
    e.tick(s(BATT, 89, 60))
    assert e.parked and h.jobs["j1"]["state"] == "paused" and e.paused_by_us == ["j1"]
    e.tick(s(AC, 89, 90))
    assert e.state == State.ON_AC and h.jobs["j1"]["state"] == "scheduled"
    assert h.jobs["j2"]["state"] == "paused"          # never touched a job the user had paused
    assert "power is back" in h.sent[-1]


def test_keep_prevents_auto_park_at_critical():
    h = FakeHermes()
    e = Engine(cfg=Config(critical_pct=15), fx=h.fx())
    e.tick(s(BATT, 20, 0))
    e.command("keep")
    e.tick(s(BATT, 10, 30))
    assert not e.parked


def test_critical_without_answer_parks_reversibly():
    h = FakeHermes()
    e = Engine(cfg=Config(critical_pct=15), fx=h.fx())
    e.tick(s(BATT, 20, 0))
    e.tick(s(BATT, 12, 30))
    assert e.parked and h.jobs["j1"]["state"] == "paused"


def test_runway_announced_once_after_enough_data():
    h = FakeHermes()
    e = Engine(fx=h.fx())
    for i, p in enumerate([80, 79, 78, 77]):
        e.tick(s(BATT, p, i * 60))
    runway_msgs = [m for m in h.sent if "measured runway" in m]
    assert len(runway_msgs) == 1


def test_no_reading_takes_no_action():
    h = FakeHermes()
    e = Engine(fx=h.fx())
    e.tick(None)
    assert not e.parked and h.jobs["j1"]["state"] == "scheduled"


def test_failed_notify_is_logged_not_raised():
    h = FakeHermes()
    fx = h.fx()
    fx.notify = lambda t: (_ for _ in ()).throw(RuntimeError("gateway down"))
    e = Engine(fx=fx)
    e.tick(s(BATT, 50, 0))
    assert any(ev.get("event") == "notify" and ev["delivered"] is False for ev in h.events)


class FlakyNotify:
    """Fails the first `fail` sends, like a gateway mid-restart or a router that lost power."""
    def __init__(self, fail):
        self.fail, self.sent = fail, []

    def __call__(self, text):
        if self.fail > 0:
            self.fail -= 1
            return False
        self.sent.append(text)
        return True


def test_failed_alert_is_retried_next_tick_and_marked_late():
    # Real case, Nov 8: the alert fired while the gateway's Telegram deps were reinstalling.
    h = FakeHermes()
    fx, flaky = h.fx(), FlakyNotify(fail=2)
    fx.notify = flaky
    e = Engine(fx=fx)
    e.tick(s(AC, 97, 0))
    e.tick(s(BATT, 97, 5))           # alert fails
    assert not flaky.sent and len(e.outbox) == 1
    e.tick(s(BATT, 97, 10))          # retry fails
    e.tick(s(BATT, 97, 15))          # retry succeeds, under a minute: no "delayed" tag
    assert len(flaky.sent) == 1 and flaky.sent[0].startswith("Brownout: power lost") and not e.outbox


def test_outbox_keeps_order_across_power_back():
    h = FakeHermes()
    fx, flaky = h.fx(), FlakyNotify(fail=10**6)
    fx.notify = flaky
    e = Engine(fx=fx)
    e.tick(s(AC, 90, 0))
    e.tick(s(BATT, 90, 30))
    e.tick(s(AC, 90, 400))           # power back while the network is still down
    assert [m["kind"] for m in e.outbox] == ["alert", "back"]
    flaky.fail = 0
    e.tick(s(AC, 90, 430))
    assert flaky.sent[0].startswith("[delayed 6 min] Brownout: power lost")
    assert flaky.sent[1] == "Brownout: power is back after 6 min on battery. Nothing was parked."
    assert not e.outbox


def test_outbox_drops_messages_older_than_an_hour():
    h = FakeHermes()
    fx, flaky = h.fx(), FlakyNotify(fail=10**6)
    fx.notify = flaky
    e = Engine(fx=fx)
    e.tick(s(BATT, 90, 0))
    flaky.fail = 0
    e.tick(s(BATT, 80, 3700))
    assert not any("power lost" in m for m in flaky.sent)
    assert any(ev.get("event") == "notify_dropped" and ev["kind"] == "alert" for ev in h.events)


def test_alert_without_os_estimate_reads_cleanly():
    h = FakeHermes()
    e = Engine(fx=h.fx())
    e.tick(s(AC, 97, 0))
    e.tick(parse_pmset("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t97%; discharging; "
                       "(no estimate) present: true", t=5))
    assert "Battery 97%. Measuring the real drain now." in h.sent[0]


def test_replay_runs_with_no_effects(tmp_path):
    trace = tmp_path / "t.jsonl"
    lines = [(0, AC, 90), (30, BATT, 90), (90, BATT, 89), (150, BATT, 88), (210, AC, 88)]
    trace.write_text("\n".join(json.dumps({"t": t, "pmset": r.format(p=p)}) for t, r, p in lines))
    out = replay(trace, commands={2: "park"})
    text = "\n".join(out)
    assert "[would send] Brownout: power lost" in text
    assert "parked" in text and "power is back" in text


def test_whole_percent_plateaus_do_not_forecast_days():
    # Shape of real run 2 on this Mac (Nov 8): 79% flat for 15 min, 78% for 8.5 min, then 77%.
    from core.forecast import runway
    from core.power import PowerSample
    pts = [(t, 79.0) for t in range(0, 894, 5)] + [(t, 78.0) for t in range(894, 1404, 5)] + \
          [(t, 77.0) for t in range(1404, 1500, 5)]
    ss = [PowerSample(t, False, p, "pmset") for t, p in pts]
    assert runway(ss).minutes is None            # two drops: not enough, and never 32,559 min
    more = ss + [PowerSample(t, False, 76.0, "pmset") for t in range(1914, 1950, 5)]
    rw = runway(more)
    assert rw.minutes is not None and 400 < rw.minutes < 900   # ~1 pt / 8.5 min -> ~10 h to 5%
