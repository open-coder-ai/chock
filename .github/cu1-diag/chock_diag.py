"""CU-1 diagnostic: trace one preToolUse payload through the installed Cursor runtime. Read-only.

usage (Git Bash, from the folder the hook would run in, e.g. the home folder):
  python chock_diag.py <plugin-dir> < payload.json
"""

import json
import os
import runpy
import sys
from pathlib import Path

plugin = Path(sys.argv[1])
scripts = plugin / "scripts"
gate = scripts / "pin-github-actions" / "gate.json"
raw = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
ns = runpy.run_path(str(scripts / "cursor.py"), run_name="chock_diag")


def show(label, value):
    sys.stdout.write(f"{label:22} {value!r}\n")


show("python", sys.version.split()[0])
show("os.name", os.name)
show("cwd", os.getcwd())
show("home", str(Path.home()))
show("GIT_* env", {k: v for k, v in os.environ.items() if k.startswith("GIT_")})
event = ns["parse"](raw)
show("event", (event.event, event.tool, event.path, event.cwd))
show("workspace_roots", ns["workspace_roots"](event))
show("workspace_root", ns["workspace_root"](event))
show("root_for(gate)", ns["root_for"](gate))
root = ns["repo_root_for"](event, gate)
show("repo_root_for", str(root))
writes = ns["writes_for"](event, gate, root=root)
show("writes keys", list(writes or {}))
show("repo_paths", [ns["repo_paths"](p, root) for p in (writes or {})])
outside = ns["outside_globs"](gate)
judged = ns["judged_files"](writes or {}, root, outside, lambda p: ns["repo_paths"](p, root))
show("judged keys", list(judged))
show("runner", str(ns["runner_for"](gate)))
if judged:
    deadline = ns["engine_deadline"]()
    show("run_gate", ns["run_gate"](gate, judged, "pre-tool-use", (root, {}), deadline))
show("evaluate_gate", ns["evaluate_gate"](["--gate", str(gate)], event))
wrapper = runpy.run_path(str(scripts / "chock_bundle.py"), run_name="chock_diag_wrapper")
payload = json.dumps(raw).encode("utf-8")
show("toggle wheres", [str(p) for p in wrapper["_wheres"](payload)])
show("toggle source", wrapper["source"](wrapper["_wheres"](payload)[0]))
argv = ["--bundle", "chock-witness", "--member", "pin-github-actions", str(scripts / "cursor.py"), "--gate", str(gate)]
show("wrapper argv", wrapper["wrapped"](argv, payload))
