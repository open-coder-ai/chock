"""Read-only CU-1 diagnostic: print each step of the Cursor write gate for one payload (worker CU-1, 2026-10-09)."""
import json, os, runpy, sys
from pathlib import Path
plugin = Path(sys.argv[1]); scripts = plugin / "scripts"; gate = scripts / "pin-github-actions" / "gate.json"
raw = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
ns = runpy.run_path(str(scripts / "cursor.py"), run_name="chock_diag")
def show(label, value): print(f"{label:22} {value!r}")
show("python", sys.version.split()[0]); show("cwd", os.getcwd()); show("home", str(Path.home()))
show("GIT_* env", {k: v for k, v in os.environ.items() if k.startswith("GIT_")})
event = ns["parse"](raw)
show("event", (event.event, event.tool, event.path, event.cwd))
show("workspace_root", ns["workspace_root"](event)); show("root_for(gate)", ns["root_for"](gate))
root = ns["repo_root_for"](event, gate); show("repo_root_for", str(root))
writes = ns["writes_for"](event, gate, root=root) or {}
show("writes keys", list(writes)); show("repo_paths", [ns["repo_paths"](p, root) for p in writes])
judged = ns["judged_files"](writes, root, ns["outside_globs"](gate), lambda p: ns["repo_paths"](p, root))
show("judged keys", list(judged)); show("runner", str(ns["runner_for"](gate)))
if judged: show("run_gate", ns["run_gate"](gate, judged, "pre-tool-use", (root, {}), ns["engine_deadline"]()))
show("evaluate_gate", ns["evaluate_gate"](["--gate", str(gate)], event))
w = runpy.run_path(str(scripts / "chock_bundle.py"), run_name="chock_diag_wrapper"); payload = json.dumps(raw).encode()
show("toggle source", w["source"](w["_wheres"](payload)[0]))
show("wrapper argv", w["wrapped"](["--bundle", "chock-witness", "--member", "pin-github-actions", str(scripts / "cursor.py"), "--gate", str(gate)], payload))
