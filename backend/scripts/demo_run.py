"""Runs every sample invoice in order against a live API and prints the decision + non-passing checks.
Usage: uv run python scripts/demo_run.py [base_url]"""
import json, sys, time, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8077"

def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    return json.load(urllib.request.urlopen(req))

call("/api/reset", "POST")
for name in call("/api/samples"):
    run = call(f"/api/samples/{name}/run", "POST")
    while (d := call(f"/api/runs/{run['id']}"))["status"] in ("queued", "running"):
        time.sleep(2)
    print(f"\n{name}: {d['status']} -> {d['decision']}  ({d['error'] or ''})")
    for c in (d["result"] or {}).get("checks", []):
        if c["outcome"] != "pass":
            print(f"   [{c['outcome']}] {c['id']}: {c['detail'][:160]}")
    m = (d["result"] or {}).get("match", {})
    print("   match:", m.get("how"), m.get("settled_by", ""), m.get("po_number"), m.get("confidence", ""))
