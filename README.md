# Brownout

**When the power goes out, your Hermes agent stops working and messages you.**

Brownout watches the machine Hermes runs on. When mains power drops it:

1. **Tells you** on Telegram (or any Hermes messaging target) within seconds, with the battery level and the OS's time-left estimate.
2. **Measures the real drain** and sends a runway you can trust a few minutes later.
3. **Parks the agent** when you reply `/brownout park`, or by itself if the battery hits critical and you haven't answered: scheduled jobs are paused and new tool calls are held.
4. **Picks up again** when power is back: only the jobs it paused are resumed, and you get a message.

Nothing is killed, deleted or stopped mid-write. Every park is undone on resume.

Built for places where the grid is unreliable (it was built in Lagos), and for anyone running Hermes on a laptop, a home server or behind a UPS.

## Quick start

```bash
hermes plugins install brownout --enable            # from the Hermes plugin catalog
hermes send --to telegram "test"                     # make sure Hermes can reach your phone
hermes gateway run                                   # Brownout watches from the running gateway
```

**Do this:** unplug the charger. **See this:** at the next power poll (every 15 s by default) plus a
few seconds to send (2.5–4.8 s in our runs), your phone gets
"Brownout: power lost on this machine. Battery 79%. The OS estimates 2:55 left…".
Reply `/brownout park`. Plug back in and you get "power is back. Resumed 1 job(s)…".

No hardware to unplug? Replay a real recorded outage, with no keys and no side effects:

```
/brownout replay traces/mac-20261108.jsonl
```

## Commands

| Command | What it does |
|---|---|
| `/brownout status` | Power source, charge, runway, what Brownout has paused |
| `/brownout park` | Pause active scheduled jobs and hold new tool calls |
| `/brownout keep` | Carry on; do not auto-park at critical for this outage |
| `/brownout resume` | Undo the park now |
| `/brownout test-alert` | Send a test message to your notify target |
| `/brownout replay <trace>` | Dry run over a recorded power trace |

## Settings (`plugins.entries.brownout.settings`)

| Key | Default | Meaning |
|---|---|---|
| `notify_target` | `telegram` | Any `hermes send --to` target |
| `poll_seconds` | `15` | How often power is read |
| `critical_pct` / `critical_minutes` | `15` / `10` | Auto-park threshold if you haven't answered |
| `auto_resume` | `true` | Resume automatically on power back |
| `ups` | `null` | NUT UPS name (`upsc`) for desktops and servers |

## How it works

- **Power readers:** `pmset -g batt` (macOS), `/sys/class/power_supply` (Linux), `upsc` (NUT UPS). If no reading is available Brownout takes no action, never guesses.
- **Runway:** OS charge is reported in whole percents, so Brownout measures time between percent drops instead of fitting a line through flat readings. It stays silent until it has seen real drain.
- **Parking:** pauses jobs through Hermes' `cronjob_manage` tool and holds tool calls with a `pre_tool_call` hook. It stops the *next* call; it does not interrupt a call already running.
- **Alerts:** through the documented `hermes send` CLI, using your gateway's own credentials. If a send fails (the router often goes down with the power), the message waits in an in-order queue and is retried every poll, tagged `[delayed N min]` when late. Messages over an hour old are dropped and logged rather than sent stale.

## Disclosure

One background thread per Hermes home polls power. It runs `pmset`/`upsc` locally and `hermes send` for alerts. It makes no network calls of its own and writes only to `<HERMES_HOME>/plugin-data/brownout/`.

## Development

```bash
python -m pytest -q tests
```

Every public claim and the run behind it is in [CLAIMS.md](CLAIMS.md).

MIT licensed.
