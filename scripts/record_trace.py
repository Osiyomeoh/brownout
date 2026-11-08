"""Record real power samples from this machine to a JSONL trace (one line per sample)."""
import json, subprocess, sys, time, datetime
out, every = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 30
with open(out, "a") as f:
    while True:
        raw = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
        f.write(json.dumps({"t": time.time(), "iso": datetime.datetime.now().astimezone().isoformat(), "pmset": raw}) + "\n"); f.flush()
        time.sleep(every)
