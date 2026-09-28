"""Disposable host fault probe, manually selected only in the generated pilot hooks."""
import sys
import time

mode = sys.argv[1]
if mode == "timeout":
    time.sleep(30)
elif mode == "invalid":
    print("not JSON")
elif mode in {"exit1", "exit2"}:
    print("Synthetic pilot hook failure", file=sys.stderr)
    raise SystemExit(int(mode[-1]))
else:
    raise SystemExit("Unknown fault probe")
