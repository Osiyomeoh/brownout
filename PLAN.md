# Plan

Deadline: Nov 11, 17:00 EST = 23:00 Lagos. Feature freeze: Nov 10, 23:00 Lagos.

## Done (Nov 7–8)
- Kill test: plugin pauses a real cron job and blocks tool calls in real Hermes.
- Power readers (pmset, sysfs, NUT), engine, policy, replay, 31 unit tests.
- `hermes plugins validate`: ok, no warnings (alerts via `hermes send`, not a private import).
- Two real unplug runs on this Mac; fixed whole-percent forecast bug found in run 2.
- Telegram test bot delivering alerts.

## Nov 8 (rest)
- Gateway on Telegram: `/brownout park|keep|resume|status` from the phone.
- One full end-to-end unplug run; record numbers in CLAIMS.md.
- Live agent turn blocked while parked (needs a model from Sam).

## Nov 9
- `git init`, small commits (authored by Sam, asked first).
- CI running tests. Sam makes repo public; catalog YAML pinned to the SHA; validate again.

## Nov 10
- Ship kit: video script < 90 s, stills, X post, form answers, Sam's manual steps.
- Tag `main`, freeze.

## Cut list (in order, if time runs short)
1. Live agent-turn demo (fall back to the hook-level proof).
2. UPS/NUT section of README.
3. Replay command polish.
