# Claims

Every claim in the README, video and submission must appear here with the run that proves it.
Anything not proven yet is marked **[UNPROVEN]** and must not be stated publicly until it is.

| # | Claim | Evidence | Status |
|---|-------|----------|--------|
| 1 | Detects mains power loss on macOS | Live run 1 and run 2, Nov 8, MacBook (pmset). `events-run1.jsonl`, `events-run2.jsonl` | Proven |
| 2 | Alert reaches Telegram seconds after the watcher sees the unplug | Run 1: notify 2.78 s after the battery reading. Poll interval was 5 s, so worst-case unplug→alert ≈ 5 s + send time | Proven (1 run) |
| 2b | Unplug→alert in the real gateway | Run 3: alert delivered 2.61 s after the battery reading (5 s poll) | Proven (1 run) |
| 3 | Alert includes the OS's own time-left estimate, labelled as such | Run 2 alert text: "The OS estimates 2:55 left" | Proven |
| 4 | Measured runway uses real drain, not a guess, and stays silent until it has evidence | `core/forecast.py` tick-to-tick method; `test_whole_percent_plateaus_do_not_forecast_days` built from run 2's real shape | Proven (test) |
| 5 | OS estimate alone is unreliable | Run 2: macOS estimate moved from 2:55 to 7:05 within 25 min on the same idle load | Proven (1 run) |
| 6 | Parking pauses only jobs that were running, and resume restores only those | Integration test against real Hermes (commit 122fc40): job `scheduled`→`paused` (reason "brownout: host on battery")→`scheduled`; a job the user had paused stayed paused (unit test) | Proven |
| 7 | While parked, new tool calls are blocked with a clear message | Integration test: `resolve_pre_tool_block("terminal", …)` returned the Brownout message; `cronjob_manage` allowed | Proven (hook level) |
| 8 | Blocks a tool call from a live agent turn | Run 4, Nov 8, gateway + Telegram, Bedrock Nova 2 Lite. On mains (14:11) the phone asked "What's in my home folder use terminal" and the agent ran `terminal` and answered (7.0 s). Unplugged + `/brownout park` (15:00:07), same question at 15:00:35: the agent called `terminal`, the hook returned the Brownout block, the call did not run, and the agent told Sam the machine was on battery and parked (session messages 28–30 in `state.db`). Sam confirmed on phone | Proven (1 run) |
| 9 | `/brownout park` sent from a phone parks work | Run 3, Nov 8, gateway + Telegram: reply parked the real job `nightly-report`; "parked" confirmation delivered 2.48 s after the command was applied. Sam confirmed on phone | Proven (1 run) |
| 10 | Auto-resume on power back sends a message | Run 3: charger back in → job resumed and "power is back" delivered 2.34 s after the AC reading. Sam confirmed on phone | Proven (1 run) |
| 11 | Passes `hermes plugins validate` with no warnings | Run Nov 8 against Hermes 122fc40 | Proven |
| 12 | Nothing is killed or deleted | Code: park only calls `cronjob_manage pause`; guard only blocks new calls | Proven (code review) |
| 13 | An alert that fails to send is retried, in order, and marked late | Real failure Nov 8 14:13: alert built but `hermes send` failed while the gateway reinstalled Telegram deps. Outbox added; `test_failed_alert_is_retried_next_tick_and_marked_late`, `test_outbox_keeps_order_across_power_back`, `test_outbox_drops_messages_older_than_an_hour` | Proven (test) |
| 14 | Power back with nothing parked still tells you | `test_power_back_without_park_says_so_once`; run 4: "power is back after 38 min on battery. Nothing was parked." delivered 3.08 s after the AC reading | Proven (test + 1 run) |
| 15 | Run 4 end to end, new code | Alert 2.65 s after the battery reading (and 4.82 s on the earlier unplug); park confirmation 2.34 s; resume message 3.07 s after the AC reading; job `nightly-report` back to `scheduled`. `traces/events-run4-agent-block.jsonl` | Proven (1 run) |
| 16 | A phone command never gets "Unknown command" because the watcher wrote state at the same moment | Seen twice live (Nov 8 15:00:10, Nov 11 05:45:25): park applied and "parked" delivered, but the reply raised FileNotFoundError on `state.tmp` and the gateway answered "Unknown command /brownout". Fix: one temp file per writer + one lock around engine work. `test_concurrent_state_writes_do_not_fail` failed 587/1200 writes before the fix, passes after | Proven (test) |

## Not claimed
- Does not freeze an agent turn that is already mid-tool-call. It stops the *next* call.
- Linux sysfs and NUT UPS readers are covered by parser tests with recorded formats only; not run on real Linux or UPS hardware.
