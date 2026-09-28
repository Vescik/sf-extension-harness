"""Non-networked sf/sfdx stub. No delegation, subprocesses, credentials or Salesforce imports."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
args = sys.argv[1:]
inventory = args == ["org", "list", "auth", "--json"]
record = {"kind": "inventory" if inventory else "operation",
          "argvSha256": hashlib.sha256(json.dumps(args).encode()).hexdigest()}
with (ROOT / ".cache/executor.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record) + "\n")
if inventory:
    mode_path = ROOT / ".cache/inventory-mode.txt"
    mode = mode_path.read_text().strip() if mode_path.exists() else "normal"
    if mode == "timeout":
        time.sleep(3)
    if mode == "error":
        raise SystemExit(1)
    print((ROOT / "inventory.json").read_text(encoding="utf-8"))
else:
    print(json.dumps({"status": 0, "result": "POLICY-PILOT-STUB: no Salesforce operation performed"}))
