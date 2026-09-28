"""Exercise copied hooks and a controlled executor. This is NOT VS Code host evidence."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run() -> int:
    manifest = json.loads((ROOT / "source-manifest.json").read_text(encoding="utf-8"))
    for source, digest in manifest["sources"].items():
        if hashlib.sha256((ROOT / source).read_bytes()).hexdigest() != digest:
            raise ValueError("Copied source changed: regenerate the pilot before baseline checks")
    env = {**os.environ, **json.loads((ROOT / "pilot-environment.json").read_text(encoding="utf-8"))}
    cases = [
        ("prod-query", "sf data query -o team-alpha --query SELECT", "deny", "deny"),
        ("prod-deploy", "sf project deploy start -o team-alpha -m ApexClass:Pilot", "deny", "deny"),
        ("prod-retrieve", "sf project retrieve start -o team-alpha -m ApexClass:Pilot", "continue", "continue"),
        ("shim-retrieve", "sfdx retrieve metadata -o team-alpha -m ApexClass:Pilot", "continue", "continue"),
        ("unknown", "sf data query -o unconfigured --query SELECT", "deny", "deny"),
        ("dev-deploy", "sf project deploy start -o prod-copy -m ApexClass:Pilot", "ask", "continue"),
        ("dev-validation", "sf project deploy start -o prod-copy --dry-run -m ApexClass:Pilot", "continue", "continue"),
        ("flag-injection", "sf project retrieve start -o team-alpha --flags-dir flags", "deny", "deny"),
    ]
    results = []
    for name, command, safety, role in cases:
        actual = []
        for script, extra in (("copilot_safety_hook.py", []), ("copilot_role_guard.py", ["--role", "developer"])):
            event = {"cwd": str(ROOT), "tool_name": "execute/runInTerminal", "tool_use_id": "pilot-" + name,
                     "tool_input": {"command": command}}
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *extra],
                                  input=json.dumps(event), text=True, capture_output=True,
                                  cwd=ROOT, env=env, timeout=10, check=True)
            response = json.loads(proc.stdout)
            actual.append(response.get("hookSpecificOutput", {}).get("permissionDecision", "continue"))
        # The test driver NEVER executes ask or deny, and never calls installed Salesforce.
        executed = actual == ["continue", "continue"]
        if executed:
            subprocess.run([sys.executable, str(ROOT / "scripts/pilot_cli.py"), *shlex.split(command)[1:]],
                           cwd=ROOT, env=env, capture_output=True, check=True)
        results.append({"scenario": name, "expected": [safety, role], "actual": actual,
                        "stubExecuted": executed, "pass": actual == [safety, role]})
    report = {"kind": "local-process-test", "hostAcceptance": "NOT VERIFIED", "results": results,
              "sources": manifest["sources"], "platform": sys.platform, "python": sys.version.split()[0]}
    (ROOT / ".cache/process-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if all(result["pass"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
